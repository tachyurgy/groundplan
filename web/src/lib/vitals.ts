import { create } from 'zustand';

/** Core Web Vitals for this page view. Logged to the console in dev; shown on /engineering in every build. */
export interface Vital {
  name: string;
  value: number;
  rating: string;
}
export const useVitals = create<{ vitals: Record<string, Vital> }>(() => ({ vitals: {} }));

export function startVitals() {
  void import('web-vitals').then(({ onCLS, onINP, onLCP, onFCP, onTTFB }) => {
    const report = (m: { name: string; value: number; rating: string }) => {
      useVitals.setState((s) => ({ vitals: { ...s.vitals, [m.name]: { name: m.name, value: m.value, rating: m.rating } } }));
      if (import.meta.env.DEV)
        console.info(`[web-vitals] ${m.name}`, Math.round(m.name === 'CLS' ? m.value * 1000 : m.value) / (m.name === 'CLS' ? 1000 : 1), m.rating);
    };
    onCLS(report, { reportAllChanges: true });
    onINP(report, { reportAllChanges: true });
    onLCP(report);
    onFCP(report);
    onTTFB(report);
  });
}
