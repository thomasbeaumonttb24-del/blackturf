export default function ValueBetsLoading() {
  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-8 w-32 rounded-xl bg-gray-100 animate-pulse" />
          <div className="h-4 w-44 rounded-lg bg-gray-100 animate-pulse" />
        </div>
        <div className="flex gap-2">
          <div className="h-9 w-9 rounded-xl bg-gray-100 animate-pulse" />
          <div className="h-9 w-9 rounded-xl bg-gray-100 animate-pulse" />
        </div>
      </div>

      {/* Stats bar */}
      <div className="h-12 rounded-2xl bg-gray-100 animate-pulse" />

      {/* Filter chips */}
      <div className="flex gap-2 flex-wrap">
        {[...Array(7)].map((_, i) => (
          <div key={i} className="h-8 w-20 rounded-full bg-gray-100 animate-pulse" />
        ))}
      </div>

      {/* Cards grid */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="rounded-2xl border border-gray-200 bg-white p-5 space-y-4">
            <div className="flex items-start justify-between">
              <div className="space-y-1.5">
                <div className="h-5 w-36 rounded-lg bg-gray-100 animate-pulse" />
                <div className="h-3.5 w-24 rounded-lg bg-gray-100 animate-pulse" />
              </div>
              <div className="h-8 w-14 rounded-xl bg-gray-100 animate-pulse" />
            </div>
            <div className="space-y-2">
              <div className="h-2 w-full rounded-full bg-gray-100 animate-pulse" />
              <div className="flex justify-between">
                <div className="h-3 w-12 rounded-lg bg-gray-100 animate-pulse" />
                <div className="h-3 w-12 rounded-lg bg-gray-100 animate-pulse" />
              </div>
            </div>
            <div className="flex gap-2">
              <div className="h-6 w-16 rounded-full bg-gray-100 animate-pulse" />
              <div className="h-6 w-20 rounded-full bg-gray-100 animate-pulse" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
