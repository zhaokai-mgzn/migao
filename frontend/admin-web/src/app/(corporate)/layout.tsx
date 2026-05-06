import CorporateNav from '@/components/corporate/CorporateNav'
import CorporateFooter from '@/components/corporate/CorporateFooter'

export default function CorporateLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen flex flex-col bg-white">
      <CorporateNav />
      <main className="flex-1">{children}</main>
      <CorporateFooter />
    </div>
  )
}
