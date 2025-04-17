import pytest
from mcp_gateway.plugins.tracing.xetrack import XetrackTracingPlugin
from mcp_gateway.plugins.base import PluginContext
from tempfile import TemporaryDirectory
from xetrack import Reader
import os


@pytest.fixture(scope="module")
def temp_directory():
    """
    Fixture providing a temporary directory that persists for the module.
    """
    with TemporaryDirectory() as temp_dir:
        yield temp_dir

@pytest.fixture
def plugin(temp_directory: str) -> XetrackTracingPlugin:
    """
    Fixture providing a configured XetrackTracingPlugin instance.
    """    
    
    plugin = XetrackTracingPlugin()
    # logs_path = 'logs'
    logs_path = os.path.join(temp_directory, 'logs')
    plugin.load({"logs_path": logs_path, "db_path": temp_directory+'/tests.db'})
    return plugin

def test_xetrack_tracing(plugin: XetrackTracingPlugin, temp_directory: str
) -> None:
    """
    Test that the plugin properly processes responses and creates a valid database.
    """
    
    mock_context = PluginContext(
        server_name="test_server",
        capability_type="test_capability",
        capability_name="test_operation",
        arguments={"path": "xdss/mcp-gateway"},
        response={"_meta": None, 
                  "content": [
                      {"type": "text", "text": "[DIR] .cursor\n[DIR] .git\n[FILE] .gitignore\n[DIR] .pytest_cache\n[DIR] .venv\n[FILE] LICENSE\n[FILE] MANIFEST.in\n[FILE] README.md\n[DIR] docs\n[DIR] logs\n[DIR] mcp_gateway\n[DIR] mcp_gateway.egg-info\n[FILE] pyproject.toml\n[FILE] requirements.txt\n[DIR] tests", "annotations": None},
                      {"type": "text", "text": "a response", "annotations": {"maybe this something":"else"}}
                  ], 
                  "isError": False}
    )
    
    result = plugin.process_response(mock_context)    
    assert '_meta' in result, "Result should have _meta"
    assert 'content' in result, "Result should have content"
    assert len(result['content']) == 2, "Result should have 2 content items"
    
        
    db_path = os.path.join(temp_directory, 'tests.db')
    assert os.path.exists(db_path), f"Database file not found at {db_path}"    
    df = Reader(db=db_path).to_df()
    assert len(df)==2 , "Database is empty"
     
    logs_path = os.listdir(os.path.join(temp_directory, 'logs'))[0]
    with open(os.path.join(temp_directory, 'logs', logs_path), 'r') as f:        
        assert len(f.readlines()) > 0, "Logs file is empty"
    
