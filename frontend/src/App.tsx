import { ThemeProvider } from './components/shared/theme-provider';
import { Navigation } from './components/layout/Navigation';
import { ChatPage } from './pages/ChatPage';
import { IntelligencePage } from './pages/IntelligencePage';
import { DocumentationPage } from './pages/DocumentationPage';
import { SearchPage } from './pages/SearchPage';
import { ErrorBoundary } from './components/shared/ErrorBoundary';
import { ContractHistoryProvider } from './contexts/ContractHistoryContext';
import { useRouter } from './lib/useRouter';
import './App.css';

function App() {
  const { currentPage, navigate } = useRouter();

  const renderPage = () => {
    switch (currentPage) {
      case 'chat':
        return <ChatPage />;
      case 'intelligence':
        return <IntelligencePage />;
      case 'agents':
        return <DocumentationPage />;
      case 'search':
        return (
          <ErrorBoundary>
            <SearchPage />
          </ErrorBoundary>
        );
      default:
        return <IntelligencePage />;
    }
  };

  return (
    <ContractHistoryProvider>
      <ThemeProvider defaultTheme="light" storageKey="vite-ui-theme">
        <div className="min-h-screen bg-slate-50">
          <div className="mx-auto max-w-7xl p-6">
            <Navigation currentPage={currentPage} onNavigate={navigate} />
            {renderPage()}
          </div>
        </div>
      </ThemeProvider>
    </ContractHistoryProvider>
  );
}

export default App;