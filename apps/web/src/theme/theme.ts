import { useEffect, useState } from 'react';

export type ThemeMode = 'system' | 'light' | 'dark';

const storageKey = 'agents-swarm-theme';

export function useThemeMode() {
  const [mode, setMode] = useState<ThemeMode>(() => {
    const stored = localStorage.getItem(storageKey);
    return stored === 'light' || stored === 'dark' || stored === 'system'
      ? stored
      : 'system';
  });

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => {
      const resolved = mode === 'system' ? (media.matches ? 'dark' : 'light') : mode;
      document.documentElement.dataset.theme = resolved;
      document.documentElement.dataset.themeMode = mode;
      localStorage.setItem(storageKey, mode);
    };
    apply();
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [mode]);

  return { mode, setMode };
}
