# (bench, model, effort, per-arm cap) — one entry = ONE run; list each run twice for 2-run cells
R1 = [  # sonnet/opus/fable/astra: 1 run per bench
 ("O","github-copilot/claude-sonnet-5.5","high",1.0),
 ("IR","github-copilot/claude-sonnet-5.5","high",1.0),
 ("DR2","github-copilot/claude-sonnet-5.5","high",1.0),
 ("O","github-copilot/claude-opus-5.5","default",2.0),
 ("IR","github-copilot/claude-opus-5.5","default",2.0),
 ("DR2","github-copilot/claude-opus-5.5","default",2.0),
 ("O","github-copilot/claude-fable-5","default",2.5),
 ("IR","github-copilot/claude-fable-5","default",2.5),
 ("DR2","github-copilot/claude-fable-5","default",2.5),
 ("I2","github-copilot/claude-fable-5","default",2.5),
 ("D","github-copilot/claude-fable-5","default",2.5),
 ("O","github-copilot/gpt-6-astra","default",2.5),
 ("IR","github-copilot/gpt-6-astra","default",2.5),
 ("DR2","github-copilot/gpt-6-astra","default",2.5),
 ("I2","github-copilot/gpt-6-astra","default",2.5),
 ("D","github-copilot/gpt-6-astra","default",2.5),
]
R2 = [  # 2-run cells: each entry will be run twice
 # haiku
 *[(b,"github-copilot/claude-haiku-5.5",e,0.15) for e in ("low","medium","high") for b in ("DR2","I2","D")],
 ("DR2","github-copilot/claude-haiku-5.5","xhigh",0.15),
 # glm
 ("IR","ai-gateway-misc/fw-glm-5.3-flash","low",0.10),
 *[(b,"ai-gateway-misc/fw-glm-5.3-flash","low",0.10) for b in ("DR2","I2")],
 *[(b,"ai-gateway-misc/fw-glm-5.3-flash","high",0.10) for b in ("DR2","D")],
 # dsflash
 *[(b,"ai-gateway-misc/fw-deepseek-v4.1-flash","default",0.10) for b in ("O","IR","DR2")],
 # 1017
 *[(b,"fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017","low",0.30) for b in ("O","IR","DR2","I2","D")],
 *[(b,"fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017","medium",0.30) for b in ("O","IR","DR2")],
 *[(b,"fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017","high",0.30) for b in ("O","IR","DR2","I2","D")],
 # minimax
 *[(b,"fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash",e,0.20) for e in ("low","medium","high","xhigh") for b in ("O","IR","DR2")],
 *[(b,"fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash",e,0.20) for e in ("low","high","xhigh") for b in ("I2","D")],
 # qwen medium
 *[(b,"fireworks-ai/accounts/fireworks/models/qwen3p8-2p4t-a95b","medium",1.00) for b in ("DR2","I2","D")],
 # carbon high
 *[(b,"github-copilot/gemini-4-carbon","high",0.60) for b in ("I2","D")],
 # gem38 medium
 *[(b,"github-copilot/gemini-3.8-flash","medium",0.30) for b in ("DR2","I2","D")],
 # sol medium
 *[(b,"github-copilot/gpt-6.1-sol","medium",0.30) for b in ("DR2","I2","D")],
 # muse medium
 *[(b,"fireworks-ai/accounts/fireworks/models/muse-spark-open","medium",0.30) for b in ("O","IR","DR2","I2","D")],
 # kimi medium
 *[(b,"fireworks-ai/accounts/fireworks/models/kimi-k3p1-pro","medium",0.30) for b in ("O","IR","DR2","I2","D")],
 # hydrogen high I2 +1 (1 valid), argon high I2+1, D+1, IR+1 — single fills
 ("I2","github-copilot/gemini-4-hydrogen","high",0.60),
 ("I2","github-copilot/gemini-4-argon","high",0.60),
 ("D","github-copilot/gemini-4-argon","high",0.60),
 ("IR","github-copilot/gemini-4-argon","high",0.60),
]
ARMS = R2 + R1  # roster models first, expensive last
def runs():
    for a in R2: yield a; yield a
    for a in R1: yield a
if __name__=="__main__":
    print(sum(1 for _ in runs()), "runs")
