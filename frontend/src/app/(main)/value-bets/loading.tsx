/** Squelette des paris de valeur : même silhouette que la page. */
export default function ValueBetsLoading() {
  return (
    <div className="min-h-screen bg-background">
      <div className="border-b border-stone-200/70 bg-gradient-to-b from-[#FBF8F2] to-background">
        <div className="mx-auto max-w-7xl px-4 pb-10 pt-8 sm:px-6 sm:pb-14 sm:pt-14 lg:px-8">
          <div className="grid items-center gap-10 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:gap-16">
            <div className="space-y-4">
              <div className="h-3 w-32 rounded bg-stone-200/70 animate-pulse" />
              <div className="h-12 w-3/4 rounded-xl bg-stone-200/70 animate-pulse sm:h-16" />
              <div className="h-4 w-2/3 rounded bg-stone-200/70 animate-pulse" />
            </div>
            <div className="h-80 rounded-[1.4rem] bg-white ring-1 ring-stone-200 animate-pulse" />
          </div>
          <div className="mt-12 h-28 rounded-2xl bg-white ring-1 ring-stone-200 animate-pulse" />
        </div>
      </div>
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
        <div className="mb-6 flex flex-wrap gap-2">
          {[...Array(7)].map((_, i) => (
            <div key={i} className="h-8 w-20 rounded-full bg-stone-200/70 animate-pulse" />
          ))}
        </div>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-[26rem] rounded-2xl bg-white ring-1 ring-stone-200 animate-pulse" />
          ))}
        </div>
      </div>
    </div>
  );
}
