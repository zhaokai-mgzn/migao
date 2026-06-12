import { Lightbulb, Heart, Sprout, Lock } from 'lucide-react'

const values = [
  {
    icon: Lightbulb,
    title: '技术驱动',
    description: '持续探索AI前沿技术，将大模型能力转化为商家触手可及的智能工具',
  },
  {
    icon: Heart,
    title: '客户至上',
    description: '以商家需求为导向，让每一位用户都能感受到AI带来的效率提升',
  },
  {
    icon: Sprout,
    title: '行业深耕',
    description: '深入理解行业场景与业务逻辑，打造真正贴合实际的智能方案',
  },
  {
    icon: Lock,
    title: '数据安全',
    description: '租户级数据隔离，严格的隐私保护，让商家安心托付核心数据',
  },
]

const timeline = [
  {
    period: '2024 Q1',
    title: '项目启动',
    description: '完成技术架构设计，确定米高产品方向与AI技术路线',
  },
  {
    period: '2024 Q2',
    title: '核心引擎开发',
    description: 'AI Agent框架搭建，米宝与小布双智能助手引擎开发',
  },
  {
    period: '2024 Q3',
    title: '平台上线',
    description: '商家管理后台正式发布，米宝助手入驻管理后台，首批商家测试',
  },
  {
    period: '2024 Q4',
    title: '多渠道接入',
    description: '微信小程序上线，小布客服实现多渠道统一服务',
  },
  {
    period: '2025',
    title: '能力进化',
    description: '米宝与小布持续进化，功能扩展，服务更多行业商家',
  },
]

export default function AboutPage() {
  return (
    <>
      {/* Page Header */}
      <section className="bg-gradient-to-br from-blue-600 to-blue-800 text-white py-16 sm:py-20">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">
            关于米高
          </h1>
          <p className="mt-4 text-lg text-blue-100 max-w-2xl mx-auto">
            以AI双助手重新定义企业电商管理，让智能运营触手可及
          </p>
        </div>
      </section>

      {/* Company Intro */}
      <section className="py-20 sm:py-24 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mx-auto space-y-6 text-gray-600 leading-relaxed">
            <p>
              米高是词元通达旗下的AI智能电商管理平台，致力于为企业提供从内部运营到客户服务的一站式智能解决方案。
            </p>
            <p>
              我们深知，不同行业的企业在商品管理、订单处理、客户服务等环节面临着各自独特的挑战。传统管理模式人力成本高、响应效率低、多平台协同困难——米高正是为解决这些痛点而生。
            </p>
            <p>
              基于大语言模型技术，米高为每一位商家打造了两位AI助手：面向企业员工的「米宝」智能工作助手，和面向消费者的「小布」智能客服。米宝帮助运营团队高效处理商品管理、订单跟踪、库存盘点、售后协调等日常事务；小布则7×24小时在线，精准理解客户意图，提供专业贴心的购物咨询服务。
            </p>
            <p>
              作为SaaS平台，我们为每位商家提供独立的数据空间和个性化的AI能力，确保数据安全的同时，让AI深度学习每位商家的业务知识，提供越来越精准的智能服务。
            </p>
          </div>
        </div>
      </section>

      {/* Mission & Vision */}
      <section className="py-20 sm:py-24 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10 max-w-4xl mx-auto">
            <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100">
              <h2 className="text-xl font-bold text-gray-900 mb-4">我们的使命</h2>
              <p className="text-gray-600 leading-relaxed">
                让每一家企业都能拥有自己的AI助手团队，用智能技术消除管理能力差距，帮助中小商家也能提供大品牌级别的运营效率和客户体验。
              </p>
            </div>
            <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100">
              <h2 className="text-xl font-bold text-gray-900 mb-4">我们的愿景</h2>
              <p className="text-gray-600 leading-relaxed">
                成为企业电商领域领先的AI智能管理服务商，以「米宝+小布」双助手模式构建行业标杆，推动千万商家的数字化转型与服务升级。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Core Values */}
      <section className="py-20 sm:py-24 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <h2 className="text-2xl sm:text-3xl font-bold text-gray-900 text-center mb-12">
            核心价值观
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8 max-w-5xl mx-auto">
            {values.map((item) => (
              <div key={item.title} className="text-center p-6">
                <div className="w-14 h-14 bg-blue-50 rounded-full flex items-center justify-center mx-auto mb-4">
                  <item.icon className="w-7 h-7 text-blue-600" />
                </div>
                <h3 className="text-base font-semibold text-gray-900 mb-2">
                  {item.title}
                </h3>
                <p className="text-sm text-gray-600 leading-relaxed">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Timeline */}
      <section className="py-20 sm:py-24 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <h2 className="text-2xl sm:text-3xl font-bold text-gray-900 text-center mb-12">
            发展历程
          </h2>
          <div className="max-w-2xl mx-auto">
            <div className="relative">
              {/* Vertical line */}
              <div className="absolute left-[18px] top-2 bottom-2 w-0.5 bg-blue-200" />
              <div className="space-y-10">
                {timeline.map((item) => (
                  <div key={item.period} className="relative flex gap-6">
                    <div className="w-9 h-9 bg-blue-600 rounded-full flex items-center justify-center shrink-0 z-10">
                      <div className="w-3 h-3 bg-white rounded-full" />
                    </div>
                    <div className="pt-1">
                      <span className="text-sm font-semibold text-blue-600">
                        {item.period}
                      </span>
                      <h3 className="text-lg font-semibold text-gray-900 mt-1">
                        {item.title}
                      </h3>
                      <p className="text-sm text-gray-600 mt-1">
                        {item.description}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
    </>
  )
}
