<script lang="ts">
  import Router from "./lib/Router.svelte";
  import Route from "./lib/Route.svelte";
  import Link from "./lib/Link.svelte";
  import Home from "./pages/Home.svelte";
  import Projects from "./pages/Projects.svelte";
  import ProjectDetail from "./pages/ProjectDetail.svelte";
  import ProtocolEditor from "./pages/ProtocolEditor.svelte";
  import ExperimentRunner from "./pages/ExperimentRunner.svelte";
  import { buttonVariants } from "$lib/components/ui/button";

  // Track current route to conditionally remove container for full-bleed pages
  let currentHash = $state(window.location.hash.slice(1) || "/");
  $effect(() => {
    const handler = () => {
      currentHash = window.location.hash.slice(1) || "/";
    };
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  });

  let isFullBleed = $derived(currentHash.startsWith("/protocols/"));
</script>

<div class="min-h-screen bg-muted/40 text-foreground font-sans antialiased">
  <nav
    class="bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-b border-border px-6 py-3 flex items-center justify-between sticky top-0 z-50"
  >
    <div class="flex items-center space-x-2">
      <div
        class="w-8 h-8 bg-primary rounded-lg flex items-center justify-center text-primary-foreground font-bold shadow-sm"
      >
        R
      </div>
      <span class="text-xl font-bold tracking-tight text-foreground"
        >Runbook</span
      >
    </div>
    <div class="flex items-center space-x-4 text-sm font-medium">
      <Link
        to="/"
        class="text-muted-foreground hover:text-foreground transition-colors"
        >Dashboard</Link
      >
      <Link
        to="/projects"
        class="text-muted-foreground hover:text-foreground transition-colors"
        >Projects</Link
      >
      <Link
        to="/settings"
        class="text-muted-foreground hover:text-foreground transition-colors"
        >Settings</Link
      >
    </div>
  </nav>

  {#if isFullBleed}
    <Router>
      <Route path="/protocols/:id" component={ProtocolEditor} />
    </Router>
  {:else}
    <main class="container mx-auto py-6">
      <Router>
        <Route path="/" component={Home} />
        <Route path="/projects" component={Projects} />
        <Route path="/projects/:id" component={ProjectDetail} />
        <Route path="/protocols/:id" component={ProtocolEditor} />
        <Route path="/experiments/:id" component={ExperimentRunner} />
        <Route path="/settings">
          <div class="text-center mt-20 text-muted-foreground">
            Settings Page (Not Implemented)
          </div>
        </Route>
      </Router>
    </main>
  {/if}
</div>
