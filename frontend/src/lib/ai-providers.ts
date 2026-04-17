export interface CredentialField {
    name: string;
    label: string;
    type: 'text' | 'secret';
    required: boolean;
    placeholder?: string;
}

export interface ProviderDef {
    id: string;
    label: string;
    fields: CredentialField[];
}

export const PROVIDERS: ProviderDef[] = [
    {
        id: 'ollama',
        label: 'Ollama (Local)',
        fields: [
            { name: 'base_url', label: 'Base URL', type: 'text', required: false, placeholder: 'http://localhost:11434' },
        ],
    },
    {
        id: 'anthropic',
        label: 'Anthropic',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true, placeholder: 'sk-ant-...' },
        ],
    },
    {
        id: 'openai',
        label: 'OpenAI',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true, placeholder: 'sk-...' },
            { name: 'base_url', label: 'Base URL', type: 'text', required: false, placeholder: 'https://api.openai.com' },
        ],
    },
    {
        id: 'google',
        label: 'Google AI',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true },
        ],
    },
    {
        id: 'groq',
        label: 'Groq',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true, placeholder: 'gsk_...' },
        ],
    },
    {
        id: 'mistral',
        label: 'Mistral',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true },
        ],
    },
    {
        id: 'cohere',
        label: 'Cohere',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true },
        ],
    },
    {
        id: 'openrouter',
        label: 'OpenRouter',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true },
        ],
    },
    {
        id: 'xai',
        label: 'xAI (Grok)',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true },
        ],
    },
    {
        id: 'cerebras',
        label: 'Cerebras',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true },
        ],
    },
    {
        id: 'deepseek',
        label: 'DeepSeek',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true },
        ],
    },
    {
        id: 'together',
        label: 'Together AI',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true },
        ],
    },
    {
        id: 'fireworks',
        label: 'Fireworks AI',
        fields: [
            { name: 'api_key', label: 'API Key', type: 'secret', required: true },
        ],
    },
    {
        id: 'bedrock',
        label: 'AWS Bedrock',
        fields: [
            { name: 'aws_access_key_id', label: 'Access Key ID', type: 'secret', required: true, placeholder: 'AKIA...' },
            { name: 'aws_secret_access_key', label: 'Secret Access Key', type: 'secret', required: true },
            { name: 'region', label: 'AWS Region', type: 'text', required: true, placeholder: 'us-east-1' },
        ],
    },
];

export interface CapabilityDef {
    id: string;
    label: string;
    description: string;
}

export const CAPABILITIES: CapabilityDef[] = [
    { id: 'vision', label: 'Vision', description: 'Lab instrument image analysis' },
    { id: 'chat', label: 'Chat', description: 'AI assistant conversations' },
    { id: 'embedding', label: 'Embedding', description: 'Document search vectors' },
    { id: 'doc_structure', label: 'Document Analysis', description: 'PDF structure detection' },
    { id: 'protocol_generation', label: 'Protocol Generation', description: 'AI protocol creation' },
    { id: 'text', label: 'Text', description: 'General text generation' },
    // { id: 'audio', label: 'Audio', description: 'Speech-to-text' },  // Not yet implemented
];

export function getProviderDef(providerId: string): ProviderDef | undefined {
    return PROVIDERS.find((p) => p.id === providerId);
}
