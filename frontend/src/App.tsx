import { Button } from "./components/ui/button";

function App() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-50">
      <section className="space-y-4 text-center">
        <h1 className="text-4xl font-bold tracking-tight">Autopsy Agent</h1>
        <p className="text-slate-400">React, FastAPI, and SQLModel are ready.</p>
        <Button>Get started</Button>
      </section>
    </main>
  );
}

export default App;

