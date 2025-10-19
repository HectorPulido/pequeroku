import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import DashboardApp from '@/dashboard/DashboardApp.vue'
import LoginForm from '@/dashboard/components/LoginForm.vue'
import LoaderOverlay from '@/dashboard/components/LoaderOverlay.vue'

const containerResponse = [
  {
    id: 'vm-1',
    name: 'My VM',
    status: 'running',
    username: 'alice',
    container_type_name: 'Basic',
    created_at: '2024-05-01T00:00:00Z'
  }
]

describe('DashboardApp', () => {
  const originalFetch = globalThis.fetch
  let intervalSpy: ReturnType<typeof vi.spyOn>
  let clearIntervalSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    intervalSpy = vi.spyOn(window, 'setInterval').mockImplementation((() => 1 as unknown as number) as typeof setInterval)
    clearIntervalSpy = vi.spyOn(window, 'clearInterval').mockImplementation(() => {})
  })

  afterEach(() => {
    intervalSpy.mockRestore()
    clearIntervalSpy.mockRestore()
    if (originalFetch) {
      globalThis.fetch = originalFetch
    } else {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (globalThis as any).fetch
    }
  })

  it('logs in successfully and renders containers', async () => {
    const fetchMock = vi
      .fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>()
      .mockResolvedValueOnce(new Response('Unauthorized', { status: 401, statusText: 'Unauthorized' }))
      .mockResolvedValueOnce(new Response('{}', { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ username: 'alice', has_quota: true, quota: { credits_left: 3 } }),
          { status: 200 }
        )
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(containerResponse), { status: 200 }))

    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mount(DashboardApp, {
      global: {
        provide: {
          loaderCounter: ref(0)
        }
      }
    })

    await flushPromises()

    const loginComponent = wrapper.findComponent(LoginForm)
    expect(loginComponent.exists()).toBe(true)

    await loginComponent.find('#username').setValue('alice')
    await loginComponent.find('#password').setValue('secret')
    await loginComponent.find('form').trigger('submit.prevent')

    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(4)
    expect(wrapper.findComponent(LoginForm).exists()).toBe(false)

    const loader = wrapper.findComponent(LoaderOverlay)
    expect(loader.exists()).toBe(true)
    expect(loader.props('active')).toBe(false)

    const containerCards = wrapper.findAll('.container-card')
    expect(containerCards).toHaveLength(1)
    expect(containerCards[0].text()).toContain('My VM')
  })
})
