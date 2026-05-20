---
title: AI configuration
summary: Where AI settings live and how to choose a provider and model.
keywords: [ai, configuration, provider, model, settings, tier]
---

# AI configuration

Batchrite uses AI for several capabilities — chat conversations, specialist subagents, document search, image analysis, and more. The **AI Models** settings page lets organization admins choose which AI provider and model backs each capability. All other members can see what is configured and test connections.

## What you can do

- View the status of every AI capability (App Default, Custom, or Not Configured).
- Configure a provider and model for any capability.
- Supply API credentials for cloud providers, or point to a local Ollama instance.
- Test a configured connection before saving.
- On Pro plans, rely on platform-managed defaults without configuring anything yourself.

## Understanding subscription tiers and AI

Each capability card shows a colored badge:

- **App Default** — your organization is on a Pro or Enterprise plan and Batchrite supplies a platform-managed model. No action required.
- **Custom** — your organization has set its own provider and model for this capability.
- **Not Configured** — your organization is on the Essentials plan and has not yet set a provider for this capability. That capability will not work until configured.

On Essentials, you must supply your own provider credentials for each capability you want to use. On Pro and Enterprise, you can override the platform default for any individual capability if you prefer a different model.

## AI capabilities

| Capability | What it powers |
|---|---|
| Vision | Lab instrument image analysis |
| Chat | AI assistant conversations |
| Chat Subagent | Specialist subagents for research, protocol building, and run planning |
| Chat Summary | Condenses long chat histories when context limits are reached |
| Embedding | Document search vectors |
| Document Analysis | PDF structure detection |
| Protocol Generation | AI protocol creation |
| Text | General text generation |

## How to configure an AI provider

Only organization admins can save configuration changes. Any member can view the current configuration and run connection tests.

1. Open **Settings** from the main navigation, then click the **AI Models** tab.
2. Find the capability card you want to configure. Cards showing **Not Configured** or **App Default** have a **Configure** or **Edit** link.
3. Click **Configure** (or **Edit** if one is already set) to expand the form.
4. Choose a **Provider** from the dropdown. Available providers include Ollama (Local), Anthropic, OpenAI, Google AI, Groq, Mistral, Cohere, OpenRouter, xAI (Grok), Cerebras, DeepSeek, Together AI, Fireworks AI, and AWS Bedrock.
5. Enter the **Model Name** exactly as the provider expects it (for example, `claude-sonnet-4-20250514`).
6. Fill in any credential fields shown for the selected provider — typically an **API Key**. For Ollama, you can set a **Base URL** pointing to your local server.
7. Optionally click **Test Connection** to verify the credentials and model name before saving.
8. Click **Save** to apply the configuration.

To revert a custom configuration and go back to the platform-managed default (Pro/Enterprise only), expand the capability and click **Use App Default**.
