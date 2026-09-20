import pandas as pd
import numpy as np

from timesfm3 import TimesFM3Forecaster, ModelConfig


# ============================================================
# LOAD TIMESFM 3.0
# ============================================================

print("\nLoading TimesFM 3.0...")

config = ModelConfig(
    checkpoint_path="google/timesfm-3.0-pytorch",
    per_core_batch_size=1,
    device="cpu"
)

model = TimesFM3Forecaster(config)

print("TimesFM 3.0 loaded successfully!")


# ============================================================
# FORECAST ONE NODE
# ============================================================

def forecast_node(df, node):

    """
    Generate a TimesFM forecast for one mesh node.

    Input:
        df   -> complete sensor DataFrame
        node -> node ID, e.g. MESH_A01

    Output:
        numpy array containing the future crack forecast
    """

    # Get data for this node
    node_df = df[
        df["node_id"] == node
    ].copy()

    if node_df.empty:
        return None


    # Sort chronologically
    node_df = node_df.sort_values(
        "timestamp"
    )


    # We only need timestamp + crack displacement
    node_df = node_df[
        [
            "timestamp",
            "crack_disp_mm"
        ]
    ].copy()


    # Timestamp becomes index
    node_df = node_df.set_index(
        "timestamp"
    )


    # Convert readings into 15-minute intervals
    node_15min = (
        node_df
        .resample("15min")
        .mean()
    )


    if node_15min.empty:
        return None


    # Fill missing crack values
    node_15min["crack_disp_mm"] = (
        node_15min["crack_disp_mm"]
        .interpolate(method="linear")
    )


    # Remove remaining missing values
    valid_y = (
        node_15min["crack_disp_mm"]
        .dropna()
    )


    if len(valid_y) < 3:
        return None


    # Prepare TimesFM input
    timesfm_df = (
        node_15min
        .reset_index()
    )


    timesfm_df["unique_id"] = node


    timesfm_df = timesfm_df.rename(
        columns={
            "timestamp": "ds",
            "crack_disp_mm": "y"
        }
    )


    timesfm_df = timesfm_df[
        [
            "unique_id",
            "ds",
            "y"
        ]
    ]


    # Extract historical crack values
    context = (
        timesfm_df["y"]
        .dropna()
        .astype(np.float32)
        .values
    )


    if len(context) < 3:
        return None


    # ========================================================
    # TIMESFM PREDICTION
    # ========================================================

    outputs = list(
        model.predict_batch(
            [context],
            horizon=8,
            return_quantiles=True,
            use_symmetric_averaging=False
        )
    )


    # Return forecast values
    return outputs[0].forecast