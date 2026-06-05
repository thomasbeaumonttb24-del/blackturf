export default function ProgrammeLoading() {
  return (
    <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-8 w-36 rounded-xl bg-gray-100 animate-pulse" />
          <div className="h-4 w-48 rounded-lg bg-gray-100 animate-pulse" />
        </div>
        <div className="flex items-center gap-2">
          <div className="h-9 w-9 rounded-xl bg-gray-100 animate-pulse" />
          <div className="h-9 w-28 rounded-xl bg-gray-100 animate-pulse" />
          <div className="h-9 w-9 rounded-xl bg-gray-100 animate-pulse" />
        </div>
      </div>

      {/* Stats bar */}
      <div className="h-12 rounded-2xl bg-gray-100 animate-pulse" />

      {/* Filter chips */}
      <div className="flex gap-2">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-8 w-20 rounded-full bg-gray-100 animate-pulse" />
        ))}
      </div>

      {/* Reunion cards */}
      {[...Array(3)].map((_, i) => (
        <div key={i} className="rounded-2xl border border-gray-200 bg-white overflow-hidden">
          {/* Header */}
          <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
            <div className="h-9 w-9 rounded-xl bg-gray-100 animate-pulse" />
            <div className="flex-1 space-y-1.5">
              <div className="h-4 w-32 rounded-lg bg-gray-100 animate-pulse" />
              <div className="h-3 w-24 rounded-lg bg-gray-100 animate-pulse" />
            </div>
          </div>
          {/* Courses */}
          {[...Array(4 - i)].map((_, j) => (
            <div key={j} className="flex items-center gap-3 px-4 py-3 border-b border-gray-50 last:border-b-0">
              <div className="h-8 w-8 rounded-full bg-gray-100 animate-pulse flex-shrink-0" />
              <div className="flex-1 space-y-1.5">
                <div className="h-3.5 w-40 rounded-lg bg-gray-100 animate-pulse" />
                <div className="h-3 w-28 rounded-lg bg-gray-100 animate-pulse" />
              </div>
              <div className="space-y-1.5 flex-shrink-0">
                <div className="h-4 w-12 rounded-lg bg-gray-100 animate-pulse" />
                <div className="h-3 w-16 rounded-lg bg-gray-100 animate-pulse" />
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
