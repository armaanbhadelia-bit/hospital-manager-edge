from fastapi import FastAPI
from contextlib import asynccontextmanager
from pydantic import BaseModel
import torch
import torch.nn as nn
import numpy as np

# 1. Define the LSTM blueprint
class TelemetryLSTMAutoencoder(nn.Module):
    def __init__(self, input_dim=4, hidden_dim=16, num_layers=2):
        super(TelemetryLSTMAutoencoder, self).__init__()
        self.encoder = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True)
        self.decoder = nn.LSTM(hidden_dim, hidden_dim, num_layers, batch_first=True)
        self.output_layer = nn.Linear(hidden_dim, input_dim)

    def forward(self, x):
        _, (hidden, _) = self.encoder(x)
        seq_len = x.size(1)
        hidden_repeated = hidden[-1].unsqueeze(1).repeat(1, seq_len, 1)
        decoded_output, _ = self.decoder(hidden_repeated)
        return self.output_layer(decoded_output)

# 2. Lifespan Context Manager to load the model on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load model and constants
    checkpoint = torch.load('telemetry_autoencoder.pth', weights_only=False)
    min_val = checkpoint['min_val']
    max_val = checkpoint['max_val']

    if isinstance(min_val, torch.Tensor):
        min_val = min_val.numpy()
        max_val = max_val.numpy()

    model = TelemetryLSTMAutoencoder(input_dim=4, hidden_dim=16, num_layers=2)
    model.load_state_dict(checkpoint['model_state_dict'])
    
    # Switch to evaluation mode and turn off training specific layers
    model.eval() 
    
    # Store globally in app state
    app.state.model = model
    app.state.min_val = min_val
    app.state.max_val = max_val
    
    # The API runs its operations here
    yield 
    
    # Clean up resources when the API is shut down
    app.state.model = None

# 3. Initialize FastAPI
app = FastAPI(title="Telemetry AI API", lifespan=lifespan)
criterion = nn.MSELoss()

# 4. JSON Payload Schema
class VitalsPayload(BaseModel):
    heart_rate: float
    oxygen_saturation: float
    respiratory_rate: float
    age: float

# 5. Prediction Endpoint
@app.post("/predict")
async def predict_anomaly(vitals: VitalsPayload):
    min_val = app.state.min_val
    max_val = app.state.max_val
    
    raw_input = np.array([
        vitals.heart_rate, 
        vitals.oxygen_saturation, 
        vitals.respiratory_rate, 
        vitals.age
    ], dtype=np.float32)
    
    normalized_input = (raw_input - min_val) / (max_val - min_val + 1e-8)
    sequence = np.tile(normalized_input, (10, 1))
    tensor_input = torch.tensor(sequence, dtype=torch.float32).unsqueeze(0)
    
    # Use inference_mode for optimized computation
    with torch.inference_mode():
        reconstruction = app.state.model(tensor_input)
        loss = criterion(reconstruction, tensor_input).item()
        
    if loss < 0.05:
        status = "NORMAL"
    elif loss < 0.2:
        status = "ELEVATED"
    else:
        status = "CRITICAL"
        
    return {
        "mse_loss": round(loss, 5),
        "status": status
    }