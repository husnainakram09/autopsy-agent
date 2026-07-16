.PHONY: dev backend frontend install

dev:
	$(MAKE) backend & $(MAKE) frontend & wait

backend:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

install:
	cd backend && uv sync
	cd frontend && npm install

