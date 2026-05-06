import { MapPin, Phone, Mail, Clock } from 'lucide-react'

const contactInfo = [
  {
    icon: MapPin,
    label: '公司地址',
    value: '广东省深圳市南山区科技园xxx大厦',
  },
  {
    icon: Phone,
    label: '联系电话',
    value: '400-888-8888',
  },
  {
    icon: Mail,
    label: '电子邮箱',
    value: 'contact@migao-ai.com',
  },
  {
    icon: Clock,
    label: '工作时间',
    value: '周一至周五 9:00-18:00',
  },
]

export default function ContactPage() {
  return (
    <>
      {/* Page Header */}
      <section className="bg-gradient-to-br from-blue-600 to-blue-800 text-white py-16 sm:py-20">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">
            联系我们
          </h1>
          <p className="mt-4 text-lg text-blue-100 max-w-2xl mx-auto">
            无论您有任何疑问或合作意向，我们都期待与您取得联系
          </p>
        </div>
      </section>

      {/* Contact Content */}
      <section className="py-20 sm:py-24 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16">
            {/* Left: Contact Info */}
            <div>
              <h2 className="text-2xl font-bold text-gray-900 mb-6">
                联系信息
              </h2>
              <p className="text-gray-600 mb-8">
                欢迎通过以下方式联系我们，我们的团队将在工作时间内尽快回复您。
              </p>
              <div className="space-y-6">
                {contactInfo.map((item) => (
                  <div key={item.label} className="flex items-start gap-4">
                    <div className="w-11 h-11 bg-blue-50 rounded-lg flex items-center justify-center shrink-0">
                      <item.icon className="w-5 h-5 text-blue-600" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-500">
                        {item.label}
                      </p>
                      <p className="text-base text-gray-900 mt-0.5">
                        {item.value}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right: Contact Form */}
            <div>
              <h2 className="text-2xl font-bold text-gray-900 mb-6">
                在线留言
              </h2>
              <form className="space-y-5">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                  <div>
                    <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1.5">
                      姓名
                    </label>
                    <input
                      type="text"
                      id="name"
                      name="name"
                      placeholder="请输入您的姓名"
                      className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow"
                    />
                  </div>
                  <div>
                    <label htmlFor="phone" className="block text-sm font-medium text-gray-700 mb-1.5">
                      电话
                    </label>
                    <input
                      type="tel"
                      id="phone"
                      name="phone"
                      placeholder="请输入您的联系电话"
                      className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow"
                    />
                  </div>
                </div>
                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1.5">
                    邮箱
                  </label>
                  <input
                    type="email"
                    id="email"
                    name="email"
                    placeholder="请输入您的电子邮箱"
                    className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow"
                  />
                </div>
                <div>
                  <label htmlFor="message" className="block text-sm font-medium text-gray-700 mb-1.5">
                    留言内容
                  </label>
                  <textarea
                    id="message"
                    name="message"
                    rows={5}
                    placeholder="请输入您想咨询的内容..."
                    className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow resize-none"
                  />
                </div>
                <button
                  type="button"
                  className="w-full sm:w-auto px-8 py-3 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors shadow-sm"
                >
                  提交留言
                </button>
              </form>
            </div>
          </div>
        </div>
      </section>

      {/* Map Placeholder */}
      <section className="py-16 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="w-full h-64 bg-gray-200 rounded-xl flex items-center justify-center">
            <div className="text-center">
              <MapPin className="w-10 h-10 text-gray-400 mx-auto mb-2" />
              <p className="text-sm text-gray-500">地图加载区域</p>
            </div>
          </div>
        </div>
      </section>
    </>
  )
}
