import { useState } from 'react';
import type { FormEvent } from 'react';


interface Go2LoginProps {
  onLogin: (username: string, password: string) => Promise<void>;
}

export function Go2Login({ onLogin }: Go2LoginProps) {
  const [username, setUsername] = useState('operator');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await onLogin(username, password);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="go2-login-shell">
      <form className="go2-login-card" onSubmit={submit}>
        <div className="go2-login-mark">GO2</div>
        <h1>导航与运动控制台</h1>
        <p>外载 Jetson · 192.168.0.101</p>
        <label>
          用户名
          <input
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label>
          密码
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error && <div className="go2-login-error">{error}</div>}
        <button type="submit" disabled={busy || !password}>
          {busy ? '正在连接…' : '登录控制台'}
        </button>
        <small>所有运动指令均经过登录、控制权和失联停车保护</small>
      </form>
    </main>
  );
}
