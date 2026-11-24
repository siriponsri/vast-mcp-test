# Interactive mock smoke prompt

Paste this into a fresh T3 or Claude Code session after running setup.

> Use the registered vast MCP. Call health, then call search_gpu_offers with limit 3 and disk_gb 40. Use the first offer ID in estimate_run_cost for two hours, 1 GB upload to the host, and 2 GB download from the host. Report the tool results and whether each call succeeded. Use synthetic data only.

Expected first offer is `mock-101` and the cost is USD 0.588000. Use the Console for real quotes. Keep the PTP fallback decision separate from this connectivity check. Compare GPU, VRAM, CUDA, disk, runtime and quote before considering a move. For cross-provider research runs, preserve the commit, image, dataset and split hashes, and seed.
