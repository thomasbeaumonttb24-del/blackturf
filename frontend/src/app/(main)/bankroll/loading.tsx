export default function BankrollLoading() {
  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-8 w-36 rounded-xl bg-gray-100 animate-pulse" />
          <div className="h-4 w-28 rounded-lg bg-gray-100 animate-pulse" />
        </div>
        <div className="h-9 w-32 rounded-xl bg-gray-100 animate-pulse" />
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-2xl border border-gray-200 bg-white p-5 space-y-3">
            <div className="h-4 w-20 rounded-lg bg-gray-100 animate-pulse" />
            <div className="h-7 w-24 rounded-xl bg-gray-100 animate-pulse" />
            <div className="h-3 w-14 rounded-lg bg-gray-100 animate-pulse" />
          </div>
        ))}
      </div>

      {/* Chart */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="h-5 w-32 rounded-lg bg-gray-100 animate-pulse" />
          <div className="flex gap-1">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-7 w-12 rounded-lg bg-gray-100 animate-pulse" />
            ))}
          </div>
        </div>
        <div className="h-52 rounded-xl bg-gray-50 animate-pulse" />
      </div>

      {/* Table skeleton */}
      <div className="rounded-2xl border border-gray-200 bg-white overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
          <div className="h-9 flex-1 rounded-xl bg-gray-100 animate-pulse" />
          <div className="h-9 w-24 rounded-xl bg-gray-100 animate-pulse" />
          <div className="h-9 w-24 rounded-xl bg-gray-100 animate-pulse" />
        </div>
        {[...Array(5)].map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-5 py-3.5 border-b border-gray-50">
            <div className="h-4 w-4 rounded-full bg-gray-100 animate-pulse" />
            <div className="h-4 w-24 rounded-lg bg-gray-100 animate-pulse" />
            <div className="flex-1 h-4 w-32 rounded-lg bg-gray-100 animate-pulse" />
            <div className="h-4 w-16 rounded-lg bg-gray-100 animate-pulse" />
            <div className="h-4 w-12 rounded-lg bg-gray-100 animate-pulse" />
            <div className="h-5 w-16 rounded-full bg-gray-100 animate-pulse" />
          </div>
        ))}
      </div>
    </div>
  );
}
