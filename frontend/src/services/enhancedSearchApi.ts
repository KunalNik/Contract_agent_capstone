import { EnhancedSearchParams } from '../components/features/search/EnhancedSearchInterface';

// Same-origin requests go through the Vite proxy (dev) or the reverse proxy
// (prod); a hardcoded http://localhost:8000 broke any non-local deployment.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

export interface EnhancedSearchResponse {
  success: boolean;
  search_level: string;
  results: unknown[];
}

export interface SectionType {
  value: string;
  label: string;
  description: string;
}

class EnhancedSearchApi {
  
  async searchContracts(params: EnhancedSearchParams): Promise<EnhancedSearchResponse> {
    const response = await fetch(`${API_BASE_URL}/api/contracts/search/enhanced`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        search_level: params.searchLevel,
        query: params.query || null,
        clause_types: params.clauseTypes.length > 0 ? params.clauseTypes : null,
        section_types: params.sectionTypes.length > 0 ? params.sectionTypes : null,
        parties: params.parties.length > 0 ? params.parties : null,
        contract_type: params.contractType || null,
        active: params.active
      })
    });

    if (!response.ok) {
      throw new Error(`Search failed: ${response.statusText}`);
    }

    return response.json();
  }

  async getClauseTypes(): Promise<string[]> {
    const response = await fetch(`${API_BASE_URL}/api/contracts/search/clause-types`);
    
    if (!response.ok) {
      throw new Error(`Failed to get clause types: ${response.statusText}`);
    }

    const data = await response.json();
    return data.clause_types;
  }

  async getSectionTypes(): Promise<SectionType[]> {
    const response = await fetch(`${API_BASE_URL}/api/contracts/search/section-types`);
    
    if (!response.ok) {
      throw new Error(`Failed to get section types: ${response.statusText}`);
    }

    const data = await response.json();
    return data.section_types;
  }

  async uploadEnhancedDocument(
    file: File, 
    model: string = 'gemini-2.5-flash',
    enableEmbeddings: boolean = true
  ): Promise<any> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(
      `${API_BASE_URL}/api/documents/enhanced/upload?model=${encodeURIComponent(model)}&enable_embeddings=${enableEmbeddings}`,
      {
        method: 'POST',
        body: formData
      }
    );

    if (!response.ok) {
      throw new Error(`Enhanced upload failed: ${response.statusText}`);
    }

    return response.json();
  }

  async getEmbeddingStatus(contractId: string): Promise<any> {
    const response = await fetch(`${API_BASE_URL}/api/documents/enhanced/embedding-status/${encodeURIComponent(contractId)}`);
    
    if (!response.ok) {
      throw new Error(`Failed to get embedding status: ${response.statusText}`);
    }

    return response.json();
  }
}

export const enhancedSearchApi = new EnhancedSearchApi();