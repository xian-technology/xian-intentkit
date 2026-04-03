# Development

## Quick Start

### Local Preview (When you just want to have a quick try)
> If you decide you want to contribute to IntentKit, skip this section and run the code in your local development environment.

0. Install [Docker](https://docs.docker.com/get-started/get-docker/).

1. Clone the repository:
```bash
git clone https://github.com/xian-technology/xian-intentkit.git
cd xian-intentkit
```

2. Set up environment:
```bash
cp .env.example .env

# Edit .env file and add your configuration
# Make sure to set OPENAI_API_KEY
```

3. Start the services:
```bash
docker compose up --build
```
This will block current terminal to show logs, you can press Ctrl+C to stop it.
When you want to run other command, you can open another terminal.

4. Try it out:
```bash
curl "http://127.0.0.1:8000/debug/example/chat?q=Hello"
```
In terminal, curl cannot auto escape special characters, so you can use browser to test. Just copy the URL to your browser, replace "Hello" with your words.

5. Manage your agent:
When intentkit first starts, it will create an example agent for you. You can manage your agent by using the scripts in the `scripts` directory.
```bash
cd scripts
# Export agent
sh export.sh example
# Import agent
sh import.sh example
# Create another agent
sh create.sh my_agent
```

### Local Development
1. Clone the repository:
```bash
git clone https://github.com/xian-technology/xian-intentkit.git
cd xian-intentkit
```

2. Set up your environment:

If you haven't installed [uv](https://docs.astral.sh/uv/), please [install](https://docs.astral.sh/uv/getting-started/installation/) it first.
You don't need to worry about your Python version and venv; uv will automatically handle everything for you.
```bash
uv sync
```

3. Start the local backing services:

```bash
docker compose up -d db redis rustfs
```

4. Configure your environment:

Read [Configuration](https://intentcat.com/docs/advanced/configuration/) for detailed settings. Then create your local .env file.
```bash
cp .env.example .env
# Edit .env with your configuration
# OPENAI_API_KEY and DB_* are required
```

5. Run the application:
```bash
# Run the API server in development mode
uv run uvicorn app.api:app --reload

# Optional background services
uv run python -m app.autonomous
uv run python -m app.scheduler
```

6. Try it out:
```bash
curl "http://127.0.0.1:8000/debug/example/chat?q=Hello"
```
In terminal, curl cannot auto escape special characters, so you can use browser to test. Just copy the URL to your browser, replace "Hello" with your words.

7. Manage your agent:
When intentkit first starts, it will create an example agent for you. You can manage your agent by using the scripts in the `scripts` directory.
```bash
cd scripts
# Export agent
sh export.sh example
# Import agent
sh import.sh example
# Create another agent
sh create.sh my_agent
```

## What's Next

You can visit the [API Docs](http://localhost:8000/redoc#tag/Agent) to learn more.
For broader setup and usage documentation, see [intentcat.com/docs](https://intentcat.com/docs/).
