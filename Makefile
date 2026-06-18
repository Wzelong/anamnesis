.PHONY: build-ui deploy dev-backend dev-ui

build-ui:
	cd mcp-app && npm run build

deploy: build-ui
	git add backend/mcp_server/ui/assets
	git commit -am "deploy: rebuild UI assets" || true
	git push

dev-backend:
	cd backend && DEBUG_TOKEN_CLAIMS=1 .venv/bin/python po_main.py

dev-ui:
	cd mcp-app && npm run dev
