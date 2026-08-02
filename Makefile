.PHONY: demo demo-seed demo-down

demo:
	python3 scripts/start_demo.py

demo-seed:
	python3 scripts/start_demo.py --no-start-run

demo-down:
	docker compose -f docker-compose.yml -f docker-compose.demo.yml --profile demo down
