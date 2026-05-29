# 5. Starting the Server

Now that we have an Agent Card and an Agent Executor, we can set up and start the A2A server.

To set up an A2A server, the Python SDK provides a route factory and helper functions (`create_agent_card_routes`, `create_jsonrpc_routes`, `create_rest_routes`). Use the route factory to create routes for the A2A server's services. These routes can be attached natively to popular frameworks like [Starlette](https://www.starlette.io/) and [FastAPI](https://fastapi.tiangolo.com/), which give you better control over authentication, logging, and other features.

In this tutorial, we will use Starlette with [Uvicorn](https://www.uvicorn.org/).

## Server Setup in Helloworld

Let's look at `__main__.py` again to see how the server is initialized and started.

```python
import uvicorn

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)
from agent_executor import (
    HelloWorldAgentExecutor,  # type: ignore[import-untyped]
)
from starlette.applications import Starlette


if __name__ == '__main__':
    skill = AgentSkill(
        id='hello_world',
        name='Returns hello world',
        description='just returns hello world',
        tags=['hello world'],
        examples=['hi', 'hello world'],
    )

    extended_skill = AgentSkill(
        id='super_hello_world',
        name='Returns a SUPER Hello World',
        description='A more enthusiastic greeting, only for authenticated users.',
        tags=['hello world', 'super', 'extended'],
        examples=['super hi', 'give me a super hello'],
    )

    # This will be the public-facing agent card
    public_agent_card = AgentCard(
        name='Hello World Agent',
        description='Just a hello world agent',
        version='0.0.1',
        default_input_modes=['text/plain'],
        default_output_modes=['text/plain'],
        capabilities=AgentCapabilities(
            streaming=True, extended_agent_card=True
        ),
        supported_interfaces=[
            AgentInterface(
                protocol_binding='JSONRPC',
                url='http://127.0.0.1:9999',
            )
        ],
        skills=[skill],  # Only the basic skill for the public card
    )

    # This will be the authenticated extended agent card
    # It includes the additional 'extended_skill'
    extended_agent_card = AgentCard(
        name='Hello World Agent - Extended Edition',
        description='The full-featured hello world agent for authenticated users.',
        version='0.0.2',
        default_input_modes=['text/plain'],
        default_output_modes=['text/plain'],
        capabilities=AgentCapabilities(
            streaming=True, extended_agent_card=True
        ),
        supported_interfaces=[
            AgentInterface(
                protocol_binding='JSONRPC',
                url='http://127.0.0.1:9999',
            )
        ],
        skills=[
            skill,
            extended_skill,
        ],  # Both skills for the extended card
    )

    request_handler = DefaultRequestHandler(
        agent_executor=HelloWorldAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=public_agent_card,
        extended_agent_card=extended_agent_card,
    )

    routes = []
    routes.extend(create_agent_card_routes(public_agent_card))
    routes.extend(create_jsonrpc_routes(request_handler, '/'))

    app = Starlette(routes=routes)

    uvicorn.run(app, host='127.0.0.1', port=9999)
```

Let's break this down:

1. **`DefaultRequestHandler`**:

    - The SDK provides `DefaultRequestHandler`. This handler takes your `AgentExecutor` implementation (`HelloWorldAgentExecutor`), a `TaskStore` (`InMemoryTaskStore`), and the public and extended `AgentCard` objects.
    - It routes incoming A2A RPC calls to the appropriate methods on your executor (like `execute` or `cancel`).
    - The `TaskStore` is used by the `DefaultRequestHandler` to manage the lifecycle of tasks, especially for stateful interactions, streaming, and resubscription. Even if your agent executor is simple, the handler needs a task store.
    - `agent_card` is passed to the handler so it can verify the agent's declared capabilities when processing incoming requests. For example, it checks whether streaming or push notifications are supported before handling those request types.
    - `extended_agent_card` is passed so the handler can serve it via the `GetExtendedAgentCard` RPC method to authenticated clients.

2. **`create_agent_card_routes` and `create_jsonrpc_routes`**:

    - `create_agent_card_routes(public_agent_card)` returns Starlette routes that expose the Agent Card at the `/.well-known/agent-card.json` endpoint for public discovery.
    - `create_jsonrpc_routes(request_handler, '/')` returns Starlette routes that handle all incoming A2A JSON-RPC method calls by delegating to the `request_handler`.
    - These route lists are combined and passed to a standard `Starlette` application.

3. **`uvicorn.run(app, ...)`**:
    - The constructed `Starlette` app is run using `uvicorn.run()`, making your agent accessible over HTTP.
    - `host='127.0.0.1'` makes the server accessible only from your local machine.
    - `port=9999` specifies the port to listen on. This matches the endpoints defined in the `AgentCard`'s `supported_interfaces`.

## Running the Helloworld Server

Navigate to the `a2a-samples` directory in your terminal (if you're not already there) and ensure your virtual environment is activated.

To run the Helloworld server:

```bash
# from the a2a-samples directory
python samples/python/agents/helloworld/__main__.py
```

You should see output similar to this, indicating the server is running:

```console
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:9999 (Press CTRL+C to quit)
```

Your A2A Helloworld agent is now live and listening for requests! In the next step, we'll interact with it.
