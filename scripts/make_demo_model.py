from pathlib import Path
import torch
import torch.nn as nn
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'demo_assets'/'model_demo.pt'; out.parent.mkdir(exist_ok=True)
class TinyVision(nn.Module):
    def __init__(self):
        super().__init__(); self.net=nn.Sequential(nn.Conv2d(3,8,3,padding=1),nn.ReLU(),nn.AdaptiveAvgPool2d(1),nn.Flatten(),nn.Linear(8,2))
    def forward(self,x): return self.net(x)
model=TinyVision().eval()
example=torch.randn(1,3,64,64)
traced=torch.jit.trace(model,example)
traced.save(str(out))
print(out)
