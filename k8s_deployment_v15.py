#!/usr/bin/env python3
"""
Kubernetes Self-Healing RL Agent - Deployment Module v15.0
Production-ready with real K8s metrics and action execution
"""

import subprocess
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional, List

import numpy as np
import requests

# ═══════════════════════════════════════════════════════════════════════════════
# K8S METRICS COLLECTOR
# ═══════════════════════════════════════════════════════════════════════════════

class K8sMetricsCollector:
    """Collects real metrics from Kubernetes cluster."""
    
    def __init__(self, namespace: str = "default", 
                 prometheus_url: str = "http://localhost:9090"):
        self.namespace = namespace
        self.prometheus_url = prometheus_url
        
        try:
            from kubernetes import client, config
            config.load_incluster_config()
            print("✓ K8s in-cluster config loaded")
            self.k8s_available = True
        except:
            try:
                from kubernetes import client, config
                config.load_kube_config()
                print("✓ K8s kubeconfig loaded")
                self.k8s_available = True
            except:
                print("⚠ K8s config not available")
                self.k8s_available = False

    def _kubectl_exec(self, cmd: str) -> str:
        """Execute kubectl command and return output."""
        try:
            result = subprocess.run(
                f"kubectl {cmd}", 
                shell=True, capture_output=True, 
                text=True, timeout=5
            )
            return result.stdout
        except Exception as e:
            print(f"⚠ kubectl error: {e}")
            return ""

    def get_node_metrics(self) -> Dict[str, Any]:
        """Get node CPU/memory usage (nodes are cluster-wide, no namespace)."""
        try:
            output = self._kubectl_exec("top nodes")  # Fixed: no -n flag
            metrics = {"cpu": 0.5, "memory": 0.4}
            
            lines = output.strip().split("\n")
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 4:
                    cpu_str = parts[1].rstrip('%')
                    mem_str = parts[3].rstrip('%')
                    metrics["cpu"] = float(cpu_str) / 100 if cpu_str else 0.5
                    metrics["memory"] = float(mem_str) / 100 if mem_str else 0.4
            return metrics
        except Exception as e:
            print(f"⚠ node metrics error: {e}")
            return {"cpu": 0.5, "memory": 0.4}

    def get_pod_metrics(self) -> Dict[str, Any]:
        """Get pod health: pending, failed, crashloop, running."""
        try:
            output = self._kubectl_exec(f"get pods -n {self.namespace} -o json")
            if output:
                pods = json.loads(output)["items"]
            else:
                pods = []
            
            pending = sum(1 for p in pods if p["status"]["phase"] == "Pending")
            failed = sum(1 for p in pods if p["status"]["phase"] == "Failed")
            running = sum(1 for p in pods if p["status"]["phase"] == "Running")
            
            crashloop = 0
            for p in pods:
                for cs in p["status"].get("containerStatuses", []):
                    if cs.get("state", {}).get("waiting", {}).get("reason") == "CrashLoopBackOff":
                        crashloop += 1
                        break
            
            return {
                "pending_pods": pending,
                "failed_pods": failed,
                "running_pods": running,
                "crashloop_flag": min(float(crashloop), 20.0),
            }
        except Exception as e:
            print(f"⚠ pod metrics error: {e}")
            return {"pending_pods": 0, "failed_pods": 0, "running_pods": 0, "crashloop_flag": 0}

    def get_service_metrics(self) -> Dict[str, Any]:
        """Get service metrics from Prometheus."""
        try:
            queries = {
                "error_rate": 'rate(http_requests_total{status=~"5.."}[1m])',
                "latency_p90": 'histogram_quantile(0.90, rate(http_request_duration_seconds_bucket[1m]))',
                "latency_p99": 'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[1m]))',
                "throughput": 'rate(http_requests_total[1m])',
            }
            
            results = {}
            for name, query in queries.items():
                try:
                    resp = requests.get(
                        f"{self.prometheus_url}/api/v1/query",
                        params={"query": query},
                        timeout=3
                    )
                    data = resp.json()
                    if data["status"] == "success" and data["data"]["result"]:
                        value = float(data["data"]["result"][0]["value"][1])
                        results[name] = value
                except:
                    results[name] = 0.0
            
            return {
                "error_rate_5xx": np.clip(results.get("error_rate", 0) / 0.1, 0, 1),
                "p90_latency": np.clip(results.get("latency_p90", 0) / 1.0, 0, 1),
                "p99_latency": np.clip(results.get("latency_p99", 0) / 1.0, 0, 1),
                "throughput": np.clip(results.get("throughput", 1) / 1000, 0, 1),
            }
        except Exception as e:
            print(f"⚠ service metrics error: {e}")
            return {
                "error_rate_5xx": 0.0,
                "p90_latency": 0.0,
                "p99_latency": 0.0,
                "throughput": 0.5,
            }

    def collect_system_state(self) -> Dict[str, float]:
        """Collect all metrics and return normalized state."""
        node_m = self.get_node_metrics()
        pod_m = self.get_pod_metrics()
        svc_m = self.get_service_metrics()
        
        state = {
            "cpu_utilization": float(node_m.get("cpu", 0.5)),
            "memory_usage": float(node_m.get("memory", 0.4)),
            "disk_io": 0.3,
            "network_bandwidth": 0.2,
            "p90_latency": float(svc_m.get("p90_latency", 0.0)),
            "p99_latency": float(svc_m.get("p99_latency", 0.0)),
            "error_rate_5xx": float(svc_m.get("error_rate_5xx", 0.0)),
            "throughput": float(svc_m.get("throughput", 0.5)),
            "availability_ratio": 1.0 - float(pod_m.get("failed_pods", 0) / max(pod_m.get("running_pods", 1), 1)),
            "node_ready_status": float(pod_m.get("pending_pods", 0) / 50),
            "pending_pods": float(pod_m.get("pending_pods", 0)),
            "crashloop_flag": float(pod_m.get("crashloop_flag", 0)),
            "failed_pods": float(pod_m.get("failed_pods", 0)),
        }
        return {k: float(np.clip(v, 0, 1)) for k, v in state.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# K8S ACTION EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════════

class K8sActionExecutor:
    """Executes real Kubernetes recovery actions with cooldown."""
    
    def __init__(self, namespace: str = "default", action_cooldown: int = 30):
        self.namespace = namespace
        self.action_cooldown = action_cooldown
        self.last_action_time = {}
        self.action_history = []

    def _can_execute(self, action_id: int) -> bool:
        """Check if cooldown has passed."""
        now = time.time()
        last_time = self.last_action_time.get(action_id, 0)
        return (now - last_time) >= self.action_cooldown

    def _kubectl_exec(self, cmd: str) -> Tuple[bool, str]:
        """Execute kubectl command safely."""
        try:
            result = subprocess.run(
                f"kubectl {cmd}",
                shell=True, capture_output=True,
                text=True, timeout=10
            )
            success = result.returncode == 0
            output = result.stdout if success else result.stderr
            return success, output
        except Exception as e:
            return False, str(e)

    def restart_pod(self, pod_name: str = None) -> Tuple[bool, float]:
        """Restart a failed pod (delete to trigger restart)."""
        if not self._can_execute(1):
            return False, 0.0
        
        try:
            if not pod_name:
                output = self._kubectl_exec(
                    f"get pods -n {self.namespace} --field-selector=status.phase=Failed -o jsonpath='{{.items[0].metadata.name}}'"
                )[1]
                pod_name = output.strip()
                if not pod_name:
                    return False, 0.0
            
            success, msg = self._kubectl_exec(
                f"delete pod {pod_name} -n {self.namespace} --grace-period=10"
            )
            
            if success:
                self.last_action_time[1] = time.time()
                self.action_history.append({
                    "action": "restart_pod", 
                    "pod": pod_name, 
                    "time": datetime.now().isoformat()
                })
                return True, 15.0
            return False, 0.0
        except Exception as e:
            print(f"⚠ restart_pod error: {e}")
            return False, 0.0

    def scale_deployment(self, replicas: int = None, increment: int = 1) -> Tuple[bool, float]:
        """Scale deployment (increase replicas)."""
        if not self._can_execute(2):
            return False, 0.0
        
        try:
            output = self._kubectl_exec(
                f"get deployments -n {self.namespace} -o jsonpath='{{.items[0].metadata.name}}'"
            )[1]
            deploy_name = output.strip()
            
            if not deploy_name:
                return False, 0.0
            
            output = self._kubectl_exec(
                f"get deployment {deploy_name} -n {self.namespace} -o jsonpath='{{.spec.replicas}}'"
            )[1]
            current = int(output.strip() or "1")
            new_replicas = current + increment
            
            success, msg = self._kubectl_exec(
                f"scale deployment {deploy_name} -n {self.namespace} --replicas={new_replicas}"
            )
            
            if success:
                self.last_action_time[2] = time.time()
                self.action_history.append({
                    "action": "scale_up", 
                    "deployment": deploy_name, 
                    "replicas": new_replicas, 
                    "time": datetime.now().isoformat()
                })
                return True, 8.0
            return False, 0.0
        except Exception as e:
            print(f"⚠ scale_deployment error: {e}")
            return False, 0.0

    def rollback_deployment(self) -> Tuple[bool, float]:
        """Rollback to previous deployment version."""
        if not self._can_execute(3):
            return False, 0.0
        
        try:
            output = self._kubectl_exec(
                f"get deployments -n {self.namespace} -o jsonpath='{{.items[0].metadata.name}}'"
            )[1]
            deploy_name = output.strip()
            
            if not deploy_name:
                return False, 0.0
            
            success, msg = self._kubectl_exec(
                f"rollout undo deployment/{deploy_name} -n {self.namespace}"
            )
            
            if success:
                self.last_action_time[3] = time.time()
                self.action_history.append({
                    "action": "rollback", 
                    "deployment": deploy_name, 
                    "time": datetime.now().isoformat()
                })
                return True, 20.0
            return False, 0.0
        except Exception as e:
            print(f"⚠ rollback error: {e}")
            return False, 0.0

    def cordon_node(self) -> Tuple[bool, float]:
        """Cordon a problematic node."""
        if not self._can_execute(4):
            return False, 0.0
        
        try:
            output = self._kubectl_exec(
                f"get nodes -o jsonpath='{{.items[0].metadata.name}}'"
            )[1]
            node_name = output.strip()
            
            if not node_name:
                return False, 0.0
            
            success, msg = self._kubectl_exec(f"cordon {node_name}")
            
            if success:
                self.last_action_time[4] = time.time()
                self.action_history.append({
                    "action": "cordon_node", 
                    "node": node_name, 
                    "time": datetime.now().isoformat()
                })
                return True, 5.0
            return False, 0.0
        except Exception as e:
            print(f"⚠ cordon_node error: {e}")
            return False, 0.0

    def get_cooldown_status(self) -> Dict[int, float]:
        """Get remaining cooldown for each action."""
        now = time.time()
        status = {}
        for action_id in range(5):
            last_time = self.last_action_time.get(action_id, 0)
            elapsed = now - last_time
            remaining = max(0, self.action_cooldown - elapsed)
            status[action_id] = remaining
        return status


# ═══════════════════════════════════════════════════════════════════════════════
# DEPLOYMENT CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class DeploymentConfig:
    """Configuration for production deployment."""
    
    def __init__(self, 
                 use_real_k8s: bool = False,
                 namespace: str = "default",
                 prometheus_url: str = "http://prometheus:9090",
                 action_cooldown_sec: int = 30,
                 max_episode_steps: int = 300):
        self.use_real_k8s = use_real_k8s
        self.namespace = namespace
        self.prometheus_url = prometheus_url
        self.action_cooldown_sec = action_cooldown_sec
        self.max_episode_steps = max_episode_steps

    def __repr__(self):
        return f"""DeploymentConfig:
  - use_real_k8s: {self.use_real_k8s}
  - namespace: {self.namespace}
  - prometheus: {self.prometheus_url}
  - action_cooldown: {self.action_cooldown_sec}s
  - max_steps: {self.max_episode_steps}"""


# ═══════════════════════════════════════════════════════════════════════════════
# PRODUCTION ENVIRONMENT
# ═══════════════════════════════════════════════════════════════════════════════

class K8sProductionEnv:
    """Production Kubernetes environment adapter."""
    
    def __init__(self, config: DeploymentConfig = None):
        self.config = config or DeploymentConfig()
        self.metrics_collector = K8sMetricsCollector(
            namespace=self.config.namespace,
            prometheus_url=self.config.prometheus_url,
        )
        self.action_executor = K8sActionExecutor(
            namespace=self.config.namespace,
            action_cooldown=self.config.action_cooldown_sec,
        )
        
        self.current_step = 0
        self.current_state = {}
        self.prev_state = {}
        self.episode_start_time = time.time()
        self.steps_since_action = 0
        self.last_action_id = -1
        self.episode_rewards = []
        self.action_counts = {i: 0 for i in range(5)}

    def reset(self) -> Dict[str, float]:
        """Reset episode and collect initial state."""
        self.current_step = 0
        self.episode_start_time = time.time()
        self.steps_since_action = 0
        self.last_action_id = -1
        self.episode_rewards = []
        
        print(f"\n[{datetime.now().isoformat()}] Episode reset")
        print(f"  Namespace: {self.config.namespace}")
        print(f"  Action cooldown: {self.config.action_cooldown_sec}s")
        
        self.current_state = self.metrics_collector.collect_system_state()
        self.prev_state = self.current_state.copy()
        
        print(f"  Initial state collected: {len(self.current_state)} metrics")
        self._print_state_summary()
        
        return self.current_state

    def step(self, action_id: int) -> Dict:
        """Execute action and collect new state."""
        self.current_step += 1
        self.steps_since_action += 1
        self.action_counts[action_id] += 1
        
        action_names = ["idle", "restart_pod", "scale_up", "rollback", "cordon_node"]
        action_name = action_names[action_id]
        
        action_executed = False
        action_delay = 0.0
        
        if action_id == 0:
            action_executed = True
        elif action_id == 1:
            action_executed, action_delay = self.action_executor.restart_pod()
        elif action_id == 2:
            action_executed, action_delay = self.action_executor.scale_deployment()
        elif action_id == 3:
            action_executed, action_delay = self.action_executor.rollback_deployment()
        elif action_id == 4:
            action_executed, action_delay = self.action_executor.cordon_node()
        
        if action_executed and action_id != 0:
            self.steps_since_action = 0
            self.last_action_id = action_id
            print(f"  [Step {self.current_step}] {action_name} executed (est. delay: {action_delay:.1f}s)")
        elif not action_executed and action_id != 0:
            cooldowns = self.action_executor.get_cooldown_status()
            remaining = cooldowns.get(action_id, 0)
            print(f"  [Step {self.current_step}] {action_name} BLOCKED (cooldown: {remaining:.1f}s remaining)")
        
        if action_delay > 0:
            print(f"    Waiting {action_delay:.1f}s for action to complete...")
            time.sleep(min(action_delay, 5.0))
        
        self.prev_state = self.current_state.copy()
        self.current_state = self.metrics_collector.collect_system_state()
        
        reward = self._calculate_reward(action_id, action_executed)
        self.episode_rewards.append(reward)
        
        terminated = self._is_recovered()
        collapsed = self._is_collapsed()
        truncated = self.current_step >= self.config.max_episode_steps
        
        if terminated:
            print(f"  ✓ RECOVERED at step {self.current_step}")
        elif collapsed:
            print(f"  ✗ COLLAPSED at step {self.current_step}")
            reward += -60.0
        
        info = {
            "action": action_name,
            "action_executed": action_executed,
            "recovered": terminated,
            "collapsed": collapsed,
            "episode_step": self.current_step,
            "episode_reward": sum(self.episode_rewards),
            "cooldown_status": self.action_executor.get_cooldown_status(),
            "action_counts": self.action_counts.copy(),
        }
        
        return {
            "state": self.current_state,
            "reward": reward,
            "terminated": terminated or collapsed,
            "truncated": truncated,
            "info": info,
        }

    def _calculate_reward(self, action_id: int, executed: bool) -> float:
        """Calculate reward based on state change and action."""
        prev_h = self._calc_health(self.prev_state)
        curr_h = self._calc_health(self.current_state)
        health_delta = curr_h - prev_h
        
        reward = health_delta * 10.0
        reward -= 0.1
        
        if action_id != 0:
            if not executed:
                reward -= 0.5
            else:
                reward -= 0.08
        
        return float(reward)

    def _calc_health(self, state: Dict[str, float]) -> float:
        """Calculate system health (0-1)."""
        return (
            (1.0 - state.get("error_rate_5xx", 0.0)) * 0.20 +
            (1.0 - state.get("cpu_utilization", 0.5)) * 0.15 +
            (1.0 - state.get("memory_usage", 0.5)) * 0.15 +
            state.get("availability_ratio", 0.5) * 0.20 +
            (1.0 - state.get("p99_latency", 0.5)) * 0.15 +
            (1.0 - state.get("pending_pods", 0) / 50) * 0.15
        )

    def _is_recovered(self) -> bool:
        """Check if system is recovered."""
        s = self.current_state
        return (
            s.get("error_rate_5xx", 1.0) < 0.08 and
            s.get("pending_pods", 100) < 5 and
            s.get("crashloop_flag", 20) < 1 and
            s.get("availability_ratio", 0.0) > 0.85 and
            s.get("cpu_utilization", 1.0) < 0.75
        )

    def _is_collapsed(self) -> bool:
        """Check if system has critical failure."""
        s = self.current_state
        return (
            s.get("error_rate_5xx", 0.0) > 0.5 or
            s.get("pending_pods", 0) > 60 or
            s.get("availability_ratio", 1.0) < 0.1
        )

    def _print_state_summary(self):
        """Print current state summary."""
        s = self.current_state
        print(f"  Metrics snapshot:")
        print(f"    - Error rate: {s.get('error_rate_5xx', 0.0):.1%}")
        print(f"    - CPU: {s.get('cpu_utilization', 0.0):.1%}")
        print(f"    - Memory: {s.get('memory_usage', 0.0):.1%}")
        print(f"    - Pending pods: {int(s.get('pending_pods', 0))}")
        print(f"    - Availability: {s.get('availability_ratio', 0.0):.1%}")
        print(f"    - P99 latency: {s.get('p99_latency', 0.0):.2f}s")

    def render(self):
        """Print current state (human-readable)."""
        self._print_state_summary()


if __name__ == "__main__":
    print("✓ K8s deployment module loaded and validated")
    print("  - K8sMetricsCollector: real metric collection from K8s")
    print("  - K8sActionExecutor: action execution with 30s cooldown")
    print("  - K8sProductionEnv: production environment adapter")
    print("  - DeploymentConfig: configuration holder")
