import React, { createContext, useContext, useState, useEffect } from 'react';

interface ContractRecord {
  contract_id: string;
  filename: string;
  upload_date: string;
  model_used: string;
  analysis_completed: boolean;
  risk_score?: number;
  risk_level?: string;
  analysis_results?: any; // Cache analysis results
}

interface ContractHistoryContextType {
  contracts: ContractRecord[];
  addContract: (contract: ContractRecord) => void;
  updateContract: (contract_id: string, updates: Partial<ContractRecord>) => void;
  getContract: (contract_id: string) => ContractRecord | undefined;
  clearHistory: () => void;
  selectedContractId: string | null;
  setSelectedContract: (contract_id: string | null) => void;
}

const ContractHistoryContext = createContext<ContractHistoryContextType | undefined>(undefined);

const STORAGE_KEY = 'contract_history';

// Read once, synchronously, when the state is created. Loading in a separate effect let the
// save effect run first with an empty list, and React StrictMode's double effect run in
// development then wiped the stored history on every page reload.
const loadHistory = (): ContractRecord[] => {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
    if (!Array.isArray(parsed)) return [];
    // Invalid entries are dropped here; the save effect then rewrites storage without them
    return parsed.filter((contract: Partial<ContractRecord>) =>
      contract.contract_id &&
      contract.filename &&
      contract.upload_date &&
      contract.model_used !== undefined &&
      contract.analysis_completed !== undefined
    ) as ContractRecord[];
  } catch {
    return []; // corrupted data, or storage unavailable (private window, blocked site data)
  }
};

export const ContractHistoryProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [contracts, setContracts] = useState<ContractRecord[]>(loadHistory);
  const [selectedContractId, setSelectedContractId] = useState<string | null>(null);

  // Save to localStorage whenever contracts change with error handling
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(contracts));
    } catch {
      // If localStorage is full, remove oldest contracts
      if (contracts.length > 10) {
        const trimmed = contracts.slice(0, 10);
        setContracts(trimmed);
      }
    }
  }, [contracts]);

  const addContract = (contract: ContractRecord) => {
    setContracts(prev => {
      // Remove existing contract with same ID if it exists
      const filtered = prev.filter(c => c.contract_id !== contract.contract_id);
      return [contract, ...filtered]; // Add new contract at the beginning
    });
  };

  const updateContract = (contract_id: string, updates: Partial<ContractRecord>) => {
    setContracts(prev =>
      prev.map(contract =>
        contract.contract_id === contract_id
          ? { ...contract, ...updates }
          : contract
      )
    );
  };

  const setSelectedContract = (contract_id: string | null) => {
    setSelectedContractId(contract_id);
  };

  const getContract = (contract_id: string) => {
    return contracts.find(c => c.contract_id === contract_id);
  };

  const clearHistory = () => {
    setContracts([]);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // storage unavailable; the in-memory list is already cleared
    }
  };

  return (
    <ContractHistoryContext.Provider value={{
      contracts,
      addContract,
      updateContract,
      getContract,
      clearHistory,
      selectedContractId,
      setSelectedContract
    }}>
      {children}
    </ContractHistoryContext.Provider>
  );
};

export const useContractHistory = () => {
  const context = useContext(ContractHistoryContext);
  if (!context) {
    throw new Error('useContractHistory must be used within ContractHistoryProvider');
  }
  return context;
};