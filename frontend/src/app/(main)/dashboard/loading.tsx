/** Squelette de « Mon espace » : même silhouette que la page (en-tête sombre, puis grilles). */
export default function DashboardLoading() {
  return (
    <div className="min-h-screen bg-background">
      <div className="bg-[#0b0d12]">
        <div className="mx-auto max-w-7xl px-4 pb-8 pt-8 sm:px-6 sm:pb-12 sm:pt-12 lg:px-8">
          <div className="grid items-center gap-8 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-12">
            <div className="space-y-4">
              <div className="h-3 w-28 rounded bg-white/10 animate-pulse" />
              <div className="h-12 w-3/4 rounded-xl bg-white/10 animate-pulse sm:h-16" />
              <div className="h-4 w-40 rounded bg-white/10 animate-pulse" />
              <div className="flex gap-3 pt-2">
                <div className="h-12 w-44 rounded-xl bg-amber-400/20 animate-pulse" />
                <div className="h-12 w-40 rounded-xl bg-white/10 animate-pulse" />
              </div>
            </div>
            <div className="h-72 rounded-[1.6rem] bg-white/[0.06] ring-1 ring-white/10 animate-pulse" />
          </div>
          <div className="mt-10 grid grid-cols-2 gap-2.5 sm:gap-4 lg:grid-cols-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-[7.5rem] rounded-2xl bg-white/[0.07] ring-1 ring-white/10 animate-pulse" />
            ))}
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl space-y-12 px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 sm:gap-5">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-64 rounded-2xl bg-stone-100 animate-pulse" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="h-96 rounded-3xl bg-stone-100 animate-pulse lg:col-span-3" />
          <div className="h-96 rounded-3xl bg-stone-100 animate-pulse lg:col-span-2" />
        </div>
      </div>
    </div>
  );
}
