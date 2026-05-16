.PHONY: run-agent run-mcp run-all run-cli run-llama

# Start the hardware-accelerated local model (Port 8080)
run-llama:
	@echo "Starting Llama.cpp Server with AMD GPU acceleration..."
	HIP_VISIBLE_DEVICES=0 /home/vvolpato/llama.cpp/build/bin/llama-server -hf unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q4_K_M --port 8080 -c 16384 --cache-reuse 256 -ngl 25 -fa on --no-mmap --no-warmup --no-mmproj -np 1 --jinja

# Start only the Agent FastAPI server (Port 8000)
run-agent:
	@echo "Starting Agent FastAPI Server..."
	uv run python -m api.app.main

# Start only the FastMCP Server (Port 8081)
run-mcp:
	@echo "Starting FastMCP Server..."
	uv run python -m api.app.main_mcp

# Start the interactive chat CLI
run-cli:
	@echo "Starting Chat CLI..."
	uv run python cli.py

# Start both servers together
run-all:
	@echo "Starting FastMCP Server and Agent Server in parallel..."
	@echo "Press Ctrl+C to stop both."
	$(MAKE) -j 2 run-mcp run-agent
