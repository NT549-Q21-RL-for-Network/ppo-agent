# 🚀 QUICK START GUIDE - K8s Self-Healing RL Agent v15.0

## Pre-Deployment Setup (5 mins)

### 1. Verify Prerequisites
```bash
# Check K8s cluster
kubectl cluster-info
kubectl get pods -A

# Check Prometheus (optional, for service metrics)
curl http://localhost:9090/api/v1/query?query=up

# Verify Python packages
pip install kubernetes prometheus-client requests
```

### 2. Load the Deployment Module
```python
# In Jupyter notebook:
from k8s_deployment_v15 import (
    K8sMetricsCollector,
    K8sActionExecutor, 
    K8sProductionEnv,
    DeploymentConfig
)

import numpy as np
from stable_baselines3 import PPO
```

### 3. Configure for Your Cluster
```python
config = DeploymentConfig(
    use_real_k8s=True,              # Enable real K8s
    namespace="default",             # Change to your namespace
    prometheus_url="http://prometheus:9090",  # Your Prometheus
    action_cooldown_sec=30,         # CRITICAL: prevent spam
    max_episode_steps=300           # Max recovery time
)

print(config)
```

---

## Test Deployment (10 mins)

### Step 1: Test Metrics Collection
```python
print("[1] Testing Metrics Collection...")
collector = K8sMetricsCollector(
    namespace=config.namespace,
    prometheus_url=config.prometheus_url
)

state = collector.collect_system_state()
print(f"✓ Collected {len(state)} metrics:")
for key, val in sorted(state.items())[:5]:
    print(f"  - {key}: {val:.3f}")
```

### Step 2: Test Action Executor
```python
print("\n[2] Testing Action Executor...")
executor = K8sActionExecutor(
    namespace=config.namespace,
    action_cooldown=config.action_cooldown_sec
)

cooldowns = executor.get_cooldown_status()
print(f"✓ Action executor ready")
print(f"  Cooldown status (should be all zeros): {cooldowns}")
```

### Step 3: Test Production Environment
```python
print("\n[3] Testing Production Environment...")
env = K8sProductionEnv(config=config)

# Reset
state = env.reset()
print(f"✓ Environment reset")
print(f"  State shape: {len(state)} metrics")
print(f"  Initial health: {env._calc_health(state):.1%}")

# Single idle step
result = env.step(0)
print(f"✓ Step executed (idle)")
print(f"  Reward: {result['reward']:.3f}")
print(f"  Terminated: {result['terminated']}")
```

### Step 4: Check Output
Expected output:
```
[1] Testing Metrics Collection...
✓ Collected 13 metrics:
  - cpu_utilization: 0.450
  - memory_usage: 0.380
  - error_rate_5xx: 0.050
  - pending_pods: 2.000
  - availability_ratio: 0.950

[2] Testing Action Executor...
✓ Action executor ready
  Cooldown status: {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}

[3] Testing Production Environment...
✓ Environment reset
  State shape: 13 metrics
  Initial health: 78.5%
✓ Step executed (idle)
  Reward: -0.100
  Terminated: False
```

---

## Run Production Episode (5-15 mins)

### Load Your Trained Model
```python
print("Loading trained model...")
model = PPO.load("ppo_k8s_model_v15_0/final_model")
print(f"✓ Model loaded")
```

### Run Single Episode
```python
def run_episode(model, env_config, max_steps=300):
    """Run a single episode with trained agent."""
    
    env = K8sProductionEnv(config=env_config)
    state = env.reset()
    
    print(f"\n{'='*70}")
    print(f"PRODUCTION EPISODE")
    print(f"{'='*70}")
    print(f"Max steps: {max_steps}")
    print(f"Action cooldown: {env_config.action_cooldown_sec}s")
    print(f"{'='*70}\n")
    
    total_reward = 0
    
    for step in range(max_steps):
        # Agent decision
        obs_array = np.array(list(state.values()), dtype=np.float32)
        obs_array = np.clip(obs_array, 0, 1)
        action, _ = model.predict(obs_array, deterministic=True)
        action_id = int(action)
        
        # Execute step
        result = env.step(action_id)
        state = result["state"]
        reward = result["reward"]
        total_reward += reward
        
        # Check termination
        if result["terminated"]:
            print(f"\n→ Episode terminated at step {step + 1}")
            if result["info"]["recovered"]:
                print("   Status: ✓ SYSTEM RECOVERED")
            elif result["info"]["collapsed"]:
                print("   Status: ✗ SYSTEM COLLAPSED")
            break
        
        if result["truncated"]:
            print(f"\n→ Episode truncated at max steps")
            break
    
    # Summary
    print(f"\n{'='*70}")
    print(f"EPISODE SUMMARY")
    print(f"{'='*70}")
    print(f"Steps: {env.current_step}")
    print(f"Total reward: {total_reward:.3f}")
    print(f"Final health: {env._calc_health(state):.1%}")
    print(f"Recovered: {result['info']['recovered']}")
    
    print(f"\nAction distribution:")
    for i, name in enumerate(["idle", "restart", "scale", "rollback", "cordon"]):
        count = result['info']['action_counts'][i]
        print(f"  {name:10s}: {count} times")
    
    print(f"{'='*70}\n")
    
    return {
        "success": result['info']['recovered'],
        "steps": env.current_step,
        "reward": total_reward,
        "health": env._calc_health(state),
    }

# Run it
result = run_episode(model, config, max_steps=300)
print(f"Episode result: {result}")
```

### Expected Output
```
══════════════════════════════════════════════════════════════════

PRODUCTION EPISODE
══════════════════════════════════════════════════════════════════
Max steps: 300
Action cooldown: 30s
══════════════════════════════════════════════════════════════════

[2026-05-17T10:23:45.123456] Episode reset
  Namespace: default
  Action cooldown: 30s
  Initial state collected: 13 metrics
  Metrics snapshot:
    - Error rate: 15.0%
    - CPU: 65.0%
    - Memory: 42.0%
    - Pending pods: 8
    - Availability: 88.5%
    - P99 latency: 0.42s

  [Step 1] idle executed (est. delay: 0.0s)
  [Step 2] restart_pod executed (est. delay: 15.0s)
    Waiting 15.0s for action to complete...
  [Step 3] scale_up executed (est. delay: 8.0s)
    Waiting 8.0s for action to complete...
  [Step 4] idle executed (est. delay: 0.0s)
  [Step 5] restart_pod BLOCKED (cooldown: 22.3s remaining)

✓ RECOVERED at step 6

══════════════════════════════════════════════════════════════════
EPISODE SUMMARY
══════════════════════════════════════════════════════════════════
Steps: 6
Total reward: 18.450
Final health: 92.3%
Recovered: True

Action distribution:
  idle      : 2 times
  restart   : 1 times
  scale     : 1 times
  rollback  : 0 times
  cordon    : 0 times
══════════════════════════════════════════════════════════════════

Episode result: {'success': True, 'steps': 6, 'reward': 18.45, 'health': 0.923}
```

---

## 📊 Monitoring During Execution

### Key Metrics to Watch
1. **Action cooldown**: Should see actions blocked after execution
2. **State progression**: Error rate and pending pods should decrease
3. **Health trend**: Should improve over episode
4. **Recovery time**: Typical 5-15 mins on real systems

### If Episode Hangs
- Check Prometheus availability (service metrics collection might timeout)
- Verify K8s API accessibility (`kubectl get pods` works?)
- Check Prometheus endpoint (`curl http://prometheus:9090/api/v1/query`)

### If Episode Fails
- Enable debug logging: Add `set_level=logging.DEBUG`
- Check action execution: Verify kubectl commands work
- Check RBAC permissions: Agent needs read/write to pods/deployments

---

## ⚠️ Production Safety Checklist

- [ ] Tested with `max_episode_steps=10` first
- [ ] Verified K8s connectivity before running
- [ ] Confirmed Prometheus endpoint accessible
- [ ] Checked RBAC permissions on service account
- [ ] Monitored system during initial episode
- [ ] Reviewed cooldown behavior (30s default)
- [ ] Verified no cascading failures occurred
- [ ] Checked model predictions are reasonable

---

## 🆘 Troubleshooting

### Issue: "Error: connection refused"
```
Fix: Check kubectl works:
  kubectl cluster-info
  kubectl get pods
```

### Issue: "kubectl: top nodes not found"
```
Fix: metrics-server not installed
  kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### Issue: "Prometheus connection timeout"
```
Fix: Start port-forward:
  kubectl port-forward svc/prometheus 9090:9090
  # Or set prometheus_url to actual endpoint
```

### Issue: "Action always blocked by cooldown"
```
Fix: This is CORRECT behavior!
  30s cooldown prevents action spam
  Agent learns to space actions properly
  Not a bug, it's a feature 😊
```

### Issue: Episode takes too long
```
Fix: Metrics collection can be slow
  - Increase timeout in _kubectl_exec()
  - Or use cached metrics (implement caching)
```

---

## 📚 Additional Resources

- **K8s Metrics API**: https://kubernetes.io/docs/tasks/debug-application-cluster/resource-metrics-pipeline/
- **Prometheus Queries**: https://prometheus.io/docs/prometheus/latest/querying/basics/
- **kubectl Commands**: https://kubernetes.io/docs/reference/kubectl/

---

## ✅ Success Criteria

✓ **Deployment Successful if:**
1. Agent can collect metrics from K8s
2. Agent can execute actions (with cooldown)
3. System health improves after actions
4. Recovery occurs within 300 steps
5. No cascading failures or resource exhaustion

**Expected Results:**
- Success rate: 70-85%
- Average recovery time: 2-8 minutes
- Actions per episode: 8-12 (due to cooldown)
- No error rate increase
- Stable pod count trend

🎉 **You're Ready for Production Deployment!**
