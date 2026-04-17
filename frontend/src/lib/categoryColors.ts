/**
 * Configurable category → color mapping.
 * Adding a new category requires only a new entry here.
 */
export const categoryColors: Record<string, string> = {
    "Media Prep": "#3b82f6",
    "Cell Culture": "#10b981",
    "Reaction": "#f97316",
    "Incubate": "#f59e0b",
    "Harvest": "#8b5cf6",
    "Purification": "#ec4899",
    "Formulation": "#14b8a6",
    "Analytics": "#6366f1",
    "Quality Check": "#06b6d4",
    "Storage": "#78716c",
};

export function getCategoryColor(category: string): string {
    return categoryColors[category] || "#94a3b8";
}

/** Category icon mapping — using simple emoji icons */
export const categoryIcons: Record<string, string> = {
    "Media Prep": "🧪",
    "Cell Culture": "🧫",
    "Reaction": "⚗️",
    "Incubate": "🌡️",
    "Harvest": "🌾",
    "Purification": "💎",
    "Formulation": "📦",
    "Analytics": "📊",
    "Quality Check": "✅",
    "Storage": "❄️",
};

export function getCategoryIcon(category: string): string {
    return categoryIcons[category] || "⚙️";
}
