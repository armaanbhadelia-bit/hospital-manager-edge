"""The user's existing architecture and snapshot inference behaviour."""
import numpy as np
import torch
from torch import nn


class TelemetryLSTMAutoencoder(nn.Module):
    def __init__(self, input_dim=4, hidden_dim=16, num_layers=2):
        super().__init__()
        self.encoder = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True)
        self.decoder = nn.LSTM(hidden_dim, hidden_dim, num_layers, batch_first=True)
        self.output_layer = nn.Linear(hidden_dim, input_dim)

    def forward(self, x):
        _, (hidden, _) = self.encoder(x)
        repeated = hidden[-1].unsqueeze(1).repeat(1, x.size(1), 1)
        decoded, _ = self.decoder(repeated)
        return self.output_layer(decoded)


class Predictor:
    def __init__(self, path):
        # The supplied checkpoint contains NumPy normalization arrays. Permit
        # these specific NumPy types without enabling unrestricted pickle load.
        from numpy.core.multiarray import _reconstruct
        allowed = [_reconstruct, np.ndarray, np.dtype, type(np.dtype(np.float32))]
        with torch.serialization.safe_globals(allowed):
            checkpoint = torch.load(path, map_location='cpu', weights_only=True)
        self.min_val = np.asarray(checkpoint['min_val'], dtype=np.float32)
        self.max_val = np.asarray(checkpoint['max_val'], dtype=np.float32)
        if self.min_val.shape != (4,) or self.max_val.shape != (4,):
            raise ValueError('Checkpoint must have four normalization features')
        if not np.isfinite([self.min_val, self.max_val]).all() or np.any(self.max_val < self.min_val):
            raise ValueError('Invalid normalization constants')
        self.model = TelemetryLSTMAutoencoder()
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.model.eval()

    def predict(self, vitals):
        raw = np.array([vitals.heart_rate, vitals.oxygen_saturation,
                        vitals.respiratory_rate, vitals.age], dtype=np.float32)
        normalized = (raw - self.min_val) / (self.max_val - self.min_val + 1e-8)
        # Compatibility with the existing model: this is one snapshot repeated
        # ten times, not a claim of ten seconds of patient history.
        sequence = torch.from_numpy(np.tile(normalized, (10, 1))).unsqueeze(0)
        with torch.inference_mode():
            loss = nn.functional.mse_loss(self.model(sequence), sequence).item()
        if not np.isfinite(loss):
            raise ValueError('Model returned a non-finite score')
        status = 'NORMAL' if loss < 0.05 else 'ELEVATED' if loss < 0.2 else 'CRITICAL'
        return {'mse_loss': round(loss, 5), 'status': status}
