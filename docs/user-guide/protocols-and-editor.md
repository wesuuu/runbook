---
title: Protocols and the protocol editor
summary: How to create, edit, validate, and publish protocols using the visual editor.
keywords: [protocol, editor, swimlane, unit op, graph, publish, validate]
---

# Protocols and the protocol editor

A protocol is a reusable template for a lab process. You build it on a visual canvas by connecting unit operations (process steps) into a flow. When you run a protocol, Batchrite snapshots it into an experiment so the original template stays clean and every deviation is tracked separately.

## What you can do

- Add unit operations to the canvas by dragging them from the left sidebar.
- Connect steps by drawing edges between nodes on the canvas.
- Group steps into role swimlanes (e.g. Operator, Scientist) to show who does what.
- Set each step's parameters, duration, description, and equipment in the right-side Inspector panel.
- Switch the canvas between **↔ Horizontal** and **↕ Vertical** layout using the toolbar.
- Enable a timeline overlay (**Time: ON**) to position steps by elapsed time.
- Save work in progress with **Save Draft**, then publish when the protocol is ready.
- Preview the generated SOP and Batch Record documents with **Preview Documents**.
- Browse version history and revert to any earlier version with the **History** toolbar button.

## How to create a protocol

Protocols live inside projects. There is no standalone protocols list.

1. Open the top navigation and click **Projects**, then select a project.
2. On the project page, click the **Protocols** tab.
3. Click **+ New Protocol** (top-right of the page). Batchrite creates a new draft protocol named "Untitled Protocol" and opens the editor.
4. Click the protocol name in the left sidebar to rename it. Click the description area below the name to add a description.

## How to build the protocol graph

1. In the left sidebar, locate a unit operation under **UNIT OPERATIONS** by browsing the category groups or using the **Search ops...** field.
2. Drag the unit op from the sidebar onto the canvas. A node appears where you drop it.
3. Hover over a node's edge handle and drag to another node to connect them. Steps flow from left to right (or top to bottom in vertical layout).
4. To add a role swimlane, click **+** in the **ROLES** section of the sidebar to create a role, then drag the role onto the canvas. Unit ops dropped inside the lane are automatically assigned to that role.
5. Click any node on the canvas to open the **Inspector** panel on the right. Edits to a step's parameters, duration, and description apply to the canvas as you make them. To attach equipment, click **Manage Equipment** in the Inspector.

## How to validate and publish a protocol

1. Resolve any validation errors shown in the banner at the top of the canvas. Common issues include branches where steps are not assigned to distinct roles.
2. Click **Save Draft** in the sidebar footer to save your current work without publishing.
3. When the protocol is ready for use, click **Publish**. A dialog asks for an optional description and change summary before confirming.
4. Published protocols show a status of **Approved** and receive a version number (e.g. v1). They can be used to create runs immediately.

## How to edit a step

1. Click the step (unit op node) on the canvas. The **Inspector** panel opens on the right.
2. Edit the step's description, duration, parameters, and assigned equipment.
3. Your edits apply to the canvas immediately as you make them — there is no separate apply step. The protocol is not saved to the server until you click **Save Draft** or **Publish**.
4. Use **Ctrl+Z** (or **Cmd+Z** on Mac) to undo recent canvas changes.
