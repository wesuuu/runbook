import { Position, type Node, type Edge } from "@xyflow/svelte";

export function generateNodeId(): string {
    return globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function extractDefaultParams(paramSchema: any): Record<string, any> {
    const defaultParams: Record<string, any> = {};
    if (paramSchema?.properties) {
        for (const [key, prop] of Object.entries(
            paramSchema.properties as Record<string, any>,
        )) {
            if (prop.default !== undefined) {
                defaultParams[key] = prop.default;
            } else if (prop.enum) {
                defaultParams[key] = prop.enum[0];
            }
        }
    }
    return defaultParams;
}

export function createProcessStartNode(
    position: { x: number; y: number },
    parentId: string | undefined,
): Node {
    return {
        id: generateNodeId(),
        type: "processStart",
        zIndex: 1,
        position,
        parentId,
        width: 220,
        data: {
            label: "New Process",
            description: "",
        },
    };
}

export function createUnitOpNode(
    op: any,
    position: { x: number; y: number },
    parentId: string | undefined,
    timeEnabled: boolean,
    layout: "horizontal" | "vertical",
    pixelsPerHour: number,
): Node {
    const defaultParams = extractDefaultParams(op.param_schema);

    let nodeWidth: number | undefined;
    let nodeHeight: number | undefined;
    if (timeEnabled) {
        const sizePx = (30 / 60) * pixelsPerHour;
        if (layout === "horizontal") nodeWidth = sizePx;
        else nodeHeight = sizePx;
    }

    return {
        id: generateNodeId(),
        type: "unitOp",
        zIndex: 1,
        position,
        parentId,
        width: nodeWidth,
        height: nodeHeight,
        data: {
            label: op.name,
            unitOpId: op.id,
            category: op.category,
            description: op.description || "",
            duration_min: 30,
            params: defaultParams,
            paramSchema: op.param_schema || {},
        },
    };
}

export function createSwimLaneNode(
    role: any,
    layout: "horizontal" | "vertical",
    roleIndex: number,
    position?: { x: number; y: number },
): Node {
    const laneY = roleIndex === 0 ? 0 : roleIndex * 220;
    const laneX = 0;
    const defaultPosition =
        layout === "horizontal"
            ? { x: laneX, y: laneY }
            : { x: laneY, y: laneX };
    return {
        id: `lane-${role.id}`,
        type: "swimLane",
        zIndex: -1,
        position: position ?? defaultPosition,
        data: {
            label: role.name,
            color: role.color,
            roleId: role.id,
            orientation: layout,
        },
        style:
            layout === "horizontal"
                ? "width: 800px; height: 200px;"
                : "width: 220px; height: 500px;",
    };
}

/**
 * Update the handle orientation preset for a specific node.
 * Pass `null` to clear the per-node override and fall back to the protocol default.
 */
export function updateNodeHandleOrientation(
    nodes: Node[],
    nodeId: string,
    orientation: "horizontal" | "vertical" | null,
    protocolOrientation: "horizontal" | "vertical",
): Node[] {
    const effective = orientation ?? protocolOrientation;
    return nodes.map((n) => {
        if (n.id === nodeId && (n.type === "unitOp" || n.type === "processStart")) {
            const newData = { ...n.data };
            if (orientation === null) {
                delete newData.handleOrientation;
                delete newData.sourcePosition;
                delete newData.targetPosition;
            } else {
                newData.handleOrientation = orientation;
                delete newData.sourcePosition;
                delete newData.targetPosition;
            }
            return {
                ...n,
                data: newData,
                sourcePosition:
                    effective === "horizontal" ? Position.Right : Position.Bottom,
                targetPosition:
                    effective === "horizontal" ? Position.Left : Position.Top,
            };
        }
        return n;
    });
}

/**
 * Set an individual handle position (source or target) on a node,
 * clearing any preset orientation override.
 */
export function updateNodeHandlePosition(
    nodes: Node[],
    nodeId: string,
    handleType: "source" | "target",
    position: Position,
    protocolOrientation: "horizontal" | "vertical",
): Node[] {
    return nodes.map((n) => {
        if (n.id === nodeId && (n.type === "unitOp" || n.type === "processStart")) {
            const newData = { ...n.data };
            delete newData.handleOrientation;
            if (handleType === "source") {
                newData.sourcePosition = position;
                if (!newData.targetPosition) {
                    newData.targetPosition =
                        protocolOrientation === "horizontal"
                            ? Position.Left
                            : Position.Top;
                }
            } else {
                newData.targetPosition = position;
                if (!newData.sourcePosition) {
                    newData.sourcePosition =
                        protocolOrientation === "horizontal"
                            ? Position.Right
                            : Position.Bottom;
                }
            }
            return {
                ...n,
                data: newData,
                sourcePosition: newData.sourcePosition as Position,
                targetPosition: newData.targetPosition as Position,
            };
        }
        return n;
    });
}

/**
 * Snap a node's dimensions to timeline grid after a resize.
 * Returns updated nodes with duration_min synced to the new visual size.
 */
export function resizeNodeForTimeline(
    nodes: Node[],
    nodeId: string,
    width: number,
    height: number,
    layout: "horizontal" | "vertical",
    pixelsPerHour: number,
): Node[] {
    const sizePx = layout === "horizontal" ? width : height;
    let minutes = (sizePx / pixelsPerHour) * 60;
    minutes = Math.round(minutes / 5) * 5;
    minutes = Math.max(5, minutes);
    const snappedPx = (minutes / 60) * pixelsPerHour;
    return nodes.map((n) => {
        if (n.id !== nodeId) return n;
        return {
            ...n,
            data: { ...n.data, duration_min: minutes },
            width: layout === "horizontal" ? snappedPx : n.width,
            height: layout === "vertical" ? snappedPx : n.height,
        };
    });
}

/**
 * Remove a node from the graph, unparenting its children and cleaning up edges.
 */
export function removeNode(
    nodes: Node[],
    edges: Edge[],
    nodeId: string,
): { nodes: Node[]; edges: Edge[] } {
    const parent = nodes.find((n) => n.id === nodeId);
    const updatedNodes = nodes
        .map((n) => {
            if (n.parentId === nodeId) {
                return {
                    ...n,
                    parentId: undefined,
                    position: {
                        x: n.position.x + (parent?.position.x || 0),
                        y: n.position.y + (parent?.position.y || 0),
                    },
                };
            }
            return n;
        })
        .filter((n) => n.id !== nodeId);
    const updatedEdges = edges.filter(
        (e) => e.source !== nodeId && e.target !== nodeId,
    );
    return { nodes: updatedNodes, edges: updatedEdges };
}

/**
 * Get the next role color from the palette based on current role count.
 */
export function getNextRoleColor(roleCount: number): string {
    const colors = [
        "#3b82f6",
        "#10b981",
        "#f97316",
        "#8b5cf6",
        "#ec4899",
        "#06b6d4",
        "#f59e0b",
    ];
    return colors[roleCount % colors.length];
}
