import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { HouseholdsPage } from './pages/HouseholdsPage';
import { DashboardPage } from './pages/DashboardPage';
import { PropertyPage } from './pages/PropertyPage';
import { StrategiesPage } from './pages/StrategiesPage';
import { DocumentsPage } from './pages/DocumentsPage';
import { ReportsPage } from './pages/ReportsPage';
import { SimulatePage } from './pages/SimulatePage';
import { EvalPage } from './pages/EvalPage';

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HouseholdsPage />} />
        <Route path="/households/:id" element={<DashboardPage />} />
        <Route path="/households/:id/documents" element={<DocumentsPage />} />
        <Route path="/households/:id/reports" element={<ReportsPage />} />
        <Route path="/properties/:id" element={<PropertyPage />} />
        <Route path="/properties/:id/strategies" element={<StrategiesPage />} />
        <Route path="/simulate" element={<SimulatePage />} />
        <Route path="/eval" element={<EvalPage />} />
        <Route path="*" element={<div className="py-20 text-center text-sm text-ink-500">Not found.</div>} />
      </Route>
    </Routes>
  );
}
