#!/usr/bin/env python3
"""
ProxLB Daemon -- Dynamic Load Balancing in Proxmox Clusters including Maintenance Mode
and automatic Failover Migration when nodes fail.

Features:
  - Real API Token Management: An API token is created via the Proxmox API at first launch.
  - Continuous monitoring of cluster nodes (based on CPU and RAM).
  - If a node is in Maintenance Mode, all VMs/CTs running on it will be migrated.
  - If a node unexpectedly fails, the system attempts to automatically migrate its resources
    to healthy target nodes.
  - Configurable via the "proxlb_app.yaml" file.

Dependencies:
  pip install proxmoxer pyyaml requests

Example Configuration (proxlb_app.yaml):
------------------------------------------------
host: "proxmox.example.com"
user: "root@pam"
pass: "YourPasswordHere"
ssl_verification: False
nodes: []                  # If empty, all cluster nodes are monitored
maintenance_nodes: ["node1", "node2"]  # Nodes that should be deliberately put into maintenance mode
migration_threshold: 20    # Threshold value (score difference) in percentage points
check_interval: 300        # Cycle time in seconds (e.g., 300 = 5 minutes)
dry_run: False             # True: No actual migrations will be performed
token_file: "proxlb_token.yaml"
log_level: "INFO"          # Alternative: DEBUG for more detailed logs
------------------------------------------------

Note:
  API token creation via the API is assumed here. If this doesn't work,
  the token may need to be created manually and stored in the configuration.
  
  Author: Nico Schmidt (baGStube_Nico)
  Rewritten: 11.03.2025
  E-Mail: nico.schmidt@ns-tech.cloud
"""

import os
os.environ['NO_PROXY'] = '*'  
import sys
import time
import yaml
import random
import string
import logging
from proxmoxer import ProxmoxAPI

# Initialize logging
def init_logging(level_str):
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='[%(asctime)s] %(levelname)s: %(message)s'
    )

class ProxLBDaemon:
    def __init__(self, config):
        self.config = config
        init_logging(config.get("log_level", "INFO"))
        logging.debug("Loaded configuration: %s", self.config)
        self.token_file = config.get("token_file", "proxlb_token.yaml")
        self.check_interval = config.get("check_interval", 300)
        self.migration_threshold = config.get("migration_threshold", 20)
        self.dry_run = config.get("dry_run", False)
        self.maintenance_nodes = config.get("maintenance_nodes", [])
        self.proxmox = self.initialize_api()

    def initialize_api(self):
        # Get the configured user; fallback to "root@pam"
        config_user = self.config.get("user") or "root@pam"
        logging.debug("Loaded user: %s", config_user)
        if os.path.exists(self.token_file):
            with open(self.token_file, 'r') as f:
                token_data = yaml.safe_load(f)
            logging.debug("Token file contents: %s", token_data)
            token_id = token_data.get("api_token_id")
            token_secret = token_data.get("api_token_secret")
            if not (config_user and token_id and token_secret):
                logging.error("The token file '%s' does not contain all required values.", self.token_file)
                sys.exit(1)
            # For logging, you can display the complete API token:
            full_token = f"{config_user}!{token_id}"
            logging.info("Using found API token: %s", full_token)
            # Important: Pass only the token ID as token_name!
            return ProxmoxAPI(
                self.config['host'],
                user=config_user,
                token_name=token_id,
                token_value=token_secret,
                verify_ssl=self.config.get("ssl_verification", True),
                timeout=30
            )
        else:
            logging.info("No API token found. Creating new API token via Proxmox API...")
            try:
                proxmox_auth = ProxmoxAPI(
                    self.config['host'],
                    user=config_user,
                    password=self.config['pass'],
                    verify_ssl=self.config.get("ssl_verification", True)
                )
            except Exception as e:
                logging.error("Authentication with username/password failed: %s", e)
                sys.exit(1)
            token_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
            token_id = f"proxlb_{token_suffix}"
            try:
                token_response = proxmox_auth.access.users(config_user).token(token_id).post(
                    comment="Auto-created by ProxLB Daemon"
                )
                token_secret = token_response.get("token") or token_response.get("value")
                if not token_secret:
                    logging.error("API response did not contain a token: %s", token_response)
                    sys.exit(1)
                logging.info("New API token '%s' was successfully created.", token_id)
            except Exception as e:
                logging.error("Token creation via API failed: %s", e)
                sys.exit(1)
            token_data = {
                "api_token_user": config_user,
                "api_token_id": token_id,
                "api_token_secret": token_secret
            }
            with open(self.token_file, 'w') as f:
                yaml.safe_dump(token_data, f, default_flow_style=False)
            logging.info("New API token '%s' was saved in '%s'.", token_id, self.token_file)
            full_token = f"{config_user}!{token_id}"
            logging.info("Created API token: %s", full_token)
            return ProxmoxAPI(
                self.config['host'],
                user=config_user,
                token_name=token_id,
                token_value=token_secret,
                verify_ssl=self.config.get("ssl_verification", True)
            )

    def gather_metrics(self):
        metrics = {}
        nodes = self.config.get("nodes", [])
        if not nodes:
            try:
                nodes = [node['node'] for node in self.proxmox.nodes.get()]
            except Exception as e:
                logging.error("Error retrieving node list: %s", e)
                sys.exit(1)
        for node in nodes:
            try:
                data = self.proxmox.nodes(node).status.get()
                cpu_percent = data.get('cpu', 0) * 100
                maxmem = data.get('maxmem', 1)
                mem_percent = (data.get('mem', 0) / maxmem) * 100
                score = cpu_percent + mem_percent
                metrics[node] = {
                    "cpu_percent": cpu_percent,
                    "mem_percent": mem_percent,
                    "score": score,
                    "raw": data
                }
                logging.debug("Node %s: CPU %.2f%%, RAM %.2f%%, Score %.2f", node, cpu_percent, mem_percent, score)
            except Exception as e:
                logging.error("Error retrieving metrics for Node %s: %s", node, e)
        return metrics

    def choose_target_node(self, metrics):
        if not metrics:
            return None
        target = min(metrics.items(), key=lambda x: x[1]['score'])
        logging.info("Target node determined: %s (Score: %.2f)", target[0], target[1]["score"])
        return target[0], target[1]

    def get_vms(self, node):
        try:
            return self.proxmox.nodes(node).qemu.get()
        except Exception as e:
            logging.error("Error retrieving VM data from Node %s: %s", node, e)
            return []

    def get_cts(self, node):
        try:
            return self.proxmox.nodes(node).lxc.get()
        except Exception as e:
            logging.error("Error retrieving CT data from Node %s: %s", node, e)
            return []

    def migrate_vm(self, vm_id, source_node, target_node, force=False):
        try:
            logging.info("Starting migration of VM %s from %s to %s", vm_id, source_node, target_node)
            params = {"target": target_node, "online": 1}
            if force:
                params["force"] = True
            if self.dry_run:
                logging.info("Dry-Run: Migration of VM %s is simulated.", vm_id)
            else:
                self.proxmox.nodes(source_node).qemu(vm_id).migrate.post(**params)
                logging.info("Migration of VM %s completed.", vm_id)
        except Exception as e:
            logging.error("Error during migration of VM %s: %s", vm_id, e)

    def migrate_ct(self, ct_id, source_node, target_node, force=False):
        try:
            logging.info("Starting migration of CT %s from %s to %s", ct_id, source_node, target_node)
            params = {"target": target_node}
            if force:
                params["force"] = True
            if self.dry_run:
                logging.info("Dry-Run: Migration of CT %s is simulated.", ct_id)
            else:
                self.proxmox.nodes(source_node).lxc(ct_id).migrate.post(**params)
                logging.info("Migration of CT %s completed.", ct_id)
        except Exception as e:
            logging.error("Error during migration of CT %s: %s", ct_id, e)

    def run_balancing_cycle(self):
        logging.info("Starting a new balancing cycle...")
        metrics = self.gather_metrics()
        if not metrics:
            logging.error("No metrics available!")
            return
        target_node, target_metrics = self.choose_target_node(metrics)
        target_score = target_metrics["score"]
        for node, data in metrics.items():
            if node == target_node:
                continue
            score_diff = data["score"] - target_score
            logging.info("Node %s: Score %.2f (Difference: %.2f)", node, data["score"], score_diff)
            if score_diff >= self.migration_threshold:
                vms = self.get_vms(node)
                if vms:
                    vm_to_migrate = vms[0]
                    vm_id = vm_to_migrate.get('vmid')
                    logging.info("Node %s is more heavily loaded (Difference: %.2f). Migrating VM %s to %s.", node, score_diff, vm_id, target_node)
                    self.migrate_vm(vm_id, node, target_node)
                else:
                    logging.info("No VMs found on Node %s to migrate.", node)
            else:
                logging.info("Node %s: Load difference (%.2f) below threshold (%.2f); no migration required.", node, score_diff, self.migration_threshold)

    def handle_maintenance_and_dead_nodes(self):
        try:
            all_nodes_list = self.proxmox.nodes.get()
            all_nodes = [n["node"] for n in all_nodes_list]
        except Exception as e:
            logging.error("Error retrieving cluster nodes: %s", e)
            all_nodes = []
        alive_metrics = self.gather_metrics()
        alive_nodes = list(alive_metrics.keys())
        logging.info("Alive nodes: %s", alive_nodes)
        maintenance_nodes = self.maintenance_nodes
        logging.info("Maintenance nodes (Configuration): %s", maintenance_nodes)
        dead_nodes = [node for node in all_nodes if node not in alive_nodes]
        logging.info("Dead nodes: %s", dead_nodes)
        nodes_to_process = set(maintenance_nodes) | set(dead_nodes)
        if not nodes_to_process:
            logging.info("No nodes in maintenance/failure mode detected.")
            return
        try:
            resources = self.proxmox.cluster.resources.get()
        except Exception as e:
            logging.error("Error retrieving cluster resources: %s", e)
            resources = []
        resources_to_migrate = [
            r for r in resources if r.get("node") in nodes_to_process and r.get("type") in ["qemu", "lxc"]
        ]
        if not resources_to_migrate:
            logging.info("No VMs/CTs found on nodes in maintenance or dead mode.")
            return
        candidate_nodes = [node for node in alive_nodes if node not in maintenance_nodes]
        if not candidate_nodes:
            logging.error("No suitable target nodes available to migrate resources.")
            return
        for resource in resources_to_migrate:
            vmid = resource.get("vmid")
            res_type = resource.get("type")
            source_node = resource.get("node")
            target_node = None
            best_score = float('inf')
            for node in candidate_nodes:
                if node in alive_metrics:
                    score = alive_metrics[node]["score"]
                    if score < best_score:
                        best_score = score
                        target_node = node
            if not target_node:
                logging.error("No target node found for Resource %s (%s).", vmid, res_type)
                continue
            logging.info("Initiating migration: %s %s from %s to %s.", res_type.upper(), vmid, source_node, target_node)
            if res_type == "qemu":
                try:
                    params = {"target": target_node, "force": True}
                    if self.dry_run:
                        logging.info("Dry-run: Migration of VM %s is simulated.", vmid)
                    else:
                        self.proxmox.nodes(source_node).qemu(vmid).migrate.post(**params)
                        logging.info("Migration of VM %s completed.", vmid)
                except Exception as e:
                    logging.error("Error during migration of VM %s: %s", vmid, e)
            elif res_type == "lxc":
                try:
                    params = {"target": target_node, "force": True}
                    if self.dry_run:
                        logging.info("Dry-run: Migration of CT %s is simulated.", vmid)
                    else:
                        self.proxmox.nodes(source_node).lxc(vmid).migrate.post(**params)
                        logging.info("Migration of CT %s completed.", vmid)
                except Exception as e:
                    logging.error("Error during migration of CT %s: %s", vmid, e)

    def run_daemon(self):
        while True:
            try:
                self.handle_maintenance_and_dead_nodes()
                self.run_balancing_cycle()
            except Exception as e:
                logging.error("Unhandled exception in cycle: %s", e)
            logging.info("Waiting %s seconds until next cycle.", self.check_interval)
            time.sleep(self.check_interval)

def load_config():
    config_file = "proxlb_app.yaml"
    if not os.path.exists(config_file):
        default_config = {
            "host": "proxmox.example.com",
            "user": "root@pam",
            "pass": "YourPasswordHere",
            "ssl_verification": False,
            "nodes": [],
            "maintenance_nodes": [],
            "migration_threshold": 20,
            "check_interval": 300,
            "dry_run": False,
            "token_file": "proxlb_token.yaml",
            "log_level": "INFO"
        }
        with open(config_file, "w") as f:
            yaml.safe_dump(default_config, f, default_flow_style=False)
        logging.info("Default configuration file '%s' created. Please adjust the credentials.", config_file)
        sys.exit(0)
    else:
        with open(config_file, "r") as f:
            config = yaml.safe_load(f)
        return config

if __name__ == '__main__':
    config = load_config()
    daemon = ProxLBDaemon(config)
    daemon.run_daemon()
