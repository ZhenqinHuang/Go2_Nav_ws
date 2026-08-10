import { useMemo, useState } from 'react';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import { ConsoleClient } from './api/consoleClient';
import { Go2ControlPanel } from './components/Go2ControlPanel';
import { Go2Login } from './components/Go2Login';
import { MapView } from './components/MapView';
import { MappingPanel } from './components/MappingPanel';
import { WorkspaceChrome } from './components/WorkspaceChrome';
import { RosbridgeConnection } from './utils/RosbridgeConnection';
import { TF2JS } from './utils/tf2js';
import type { WorkspaceMode } from './types/WorkspaceMode';
import './App.css';


function App() {
  const client = useMemo(() => new ConsoleClient(), []);
  const [connection, setConnection] = useState<RosbridgeConnection | null>(null);
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>('control');
  const [webManualEnabled, setWebManualEnabled] = useState(false);
  const [hasControlLease, setHasControlLease] = useState(false);

  const login = async (username: string, password: string) => {
    await client.login(username, password);
    const ros = new RosbridgeConnection();
    if (!(await ros.connect(client.rosSocketUrl()))) {
      throw new Error('已登录，但 ROS 可视化连接失败');
    }
    setConnection(ros);
  };

  const logout = async () => {
    setWebManualEnabled(false);
    setHasControlLease(false);
    try {
      await client.logout();
    } finally {
      connection?.disconnect();
      TF2JS.getInstance().disconnect();
      setConnection(null);
    }
  };

  if (!connection) {
    return (
      <>
        <Go2Login onLogin={login} />
        <ToastContainer position="top-center" />
      </>
    );
  }

  return (
    <>
      <main className={`go2-console-shell workspace-${workspaceMode} workspace-panel-open`}>
        <MapView
          connection={connection}
          client={client}
          hasControlLease={hasControlLease}
          workspaceMode={workspaceMode}
          onWorkspaceModeChange={setWorkspaceMode}
        />
        <Go2ControlPanel
          docked
          visible={workspaceMode === 'control'}
          client={client}
          onLogout={logout}
          webManualEnabled={webManualEnabled}
          onWebManualEnabledChange={setWebManualEnabled}
          onLeaseHeldChange={setHasControlLease}
        />
        {workspaceMode === 'mapping' && (
          <MappingPanel docked client={client} connection={connection} />
        )}
        <WorkspaceChrome
          activeMode={workspaceMode}
          client={client}
          onLogout={logout}
          onModeChange={setWorkspaceMode}
          webManualEnabled={webManualEnabled}
          onWebManualEnabledChange={setWebManualEnabled}
          hasControlLease={hasControlLease}
        />
      </main>
      <ToastContainer position="top-center" />
    </>
  );
}

export default App;
