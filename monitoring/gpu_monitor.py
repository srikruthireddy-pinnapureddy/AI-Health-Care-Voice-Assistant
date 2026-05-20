from typing import Dict


def check_gpu() -> Dict[str, str]:
    try:
        import torch
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}

    if not torch.cuda.is_available():
        return {"status": "unavailable", "reason": "cuda_not_available"}

    try:
        return {
            "status": "ok",
            "device": torch.cuda.get_device_name(0),
            "memory_allocated": str(torch.cuda.memory_allocated(0)),
            "memory_reserved": str(torch.cuda.memory_reserved(0)),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
