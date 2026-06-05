export default function DashboardLoading() {
  return (
    <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header skeleton */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-8 w-48 rounded-xl bg-gray-100 animate-pulse" />
          <div className="h-4 w-32 rounded-lg bg-gray-100 animate-pulse" />
        </div>
        <div className="h-9 w-28 rounded-xl bg-gray-100 animate-pulse" />
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-2xl border border-gray-200 bg-white p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div className="h-4 w-24 rounded-lg bg-gray-100 animate-pulse" />
              <div className="h-9 w-9 rounded-xl bg-gray-100 animate-pulse" />
            </div>
            <div className="h-8 w-20 rounded-xl bg-gray-100 animate-pulse" />
            <div className="h-3 w-16 rounded-lg bg-gray-100 animate-pulse" />
          </div>
        ))}
      </div>

      {/* Main grid */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* Chart skeleton */}
        <div className="lg:col-span-2 rounded-2xl border border-gray-200 bg-white p-6 space-y-4">
          <div className="h-5 w-40 rounded-lg bg-gray-100 animate-pulse" />
          <div className="h-56 rounded-xl bg-gray-50 animate-pulse" />
        </div>
        {/* Side panel */}
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="rounded-2xl border border-gray-200 bg-white p-5 space-y-3">
              <div className="h-4 w-32 rounded-lg bg-gray-100 animate-pulse" />
              <div className="h-4 w-full rounded-lg bg-gray-100 animate-pulse" />
              <div className="h-4 w-3/4 rounded-lg bg-gray-100 animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
