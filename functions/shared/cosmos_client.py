from azure.cosmos import CosmosClient
from . import config

_container = None


def get_container():
    global _container
    if _container is not None: return _container
    client = CosmosClient.from_connection_string(config.COSMOS_CONN)
    db = client.get_database_client(config.COSMOS_DB)
    _container = db.get_container_client(config.COSMOS_CONTAINER)
    return _container


def upsert_episode(doc):
    get_container().upsert_item(doc)


def list_recent(limit=20):
    query = ("SELECT TOP @lim c.id, c.blob_name, c.timestamp, c.agent_version, "
             "c.algo, c.n_steps, c.total_reward, c.cumulative_return, "
             "c.sharpe_ratio, c.max_drawdown, c.win_rate, "
             "c.n_buy, c.n_hold, c.n_sell, c.duration_ms, c.equity_curve "
             "FROM c ORDER BY c.timestamp DESC")
    return list(get_container().query_items(
        query=query, parameters=[{"name": "@lim", "value": limit}],
        enable_cross_partition_query=True))
