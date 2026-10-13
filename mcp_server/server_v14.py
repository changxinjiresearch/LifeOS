"""Opt-in Direct v3 routing layer; legacy ASGI lifecycle remains intact."""
import asyncio
from . import server_v13 as legacy
from . import direct_v3_http as direct

async def app(scope, receive, send):
    if scope.get("type")=="lifespan":
        # IMPORTANT: the legacy MCP HTTP app owns ASGI startup/shutdown.
        # Intercepting lifespan without forwarding would break MCP transport.
        task=None
        async def wrapped_receive():
            nonlocal task
            message=await receive()
            if message["type"]=="lifespan.startup":
                if task is None:
                    task=asyncio.create_task(direct.periodic_reconcile())
            elif message["type"]=="lifespan.shutdown":
                if task is not None:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    task=None
            return message
        try:
            return await legacy.app(scope,wrapped_receive,send)
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
    if scope.get("type")=="http" and str(scope.get("path","")).startswith(direct.PREFIX+"/"):
        return await direct.handle(scope,receive,send)
    return await legacy.app(scope,receive,send)

mcp=legacy.mcp
