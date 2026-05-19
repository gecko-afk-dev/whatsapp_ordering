import { ref, computed } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import Overview from './Overview.js';
import RestaurantsAdmin from './RestaurantsAdmin.js';
import MenuManager from './MenuManager.js';
import DriversManager from './DriversManager.js';
import OrdersManager from './OrdersManager.js';
// We can dynamically render these components based on the selected tab

export default {
    template: `
        <div>
            <!-- Header -->
            <header class="bg-white border-b border-slate-200 sticky top-0 z-30">
                <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div class="flex justify-between items-center h-16">
                        <div class="flex items-center">
                            <div class="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center shadow-sm mr-3">
                                <span class="text-white font-bold text-lg leading-none">G</span>
                            </div>
                            <h1 class="text-xl font-bold text-slate-900 tracking-tight">GEQO Dashboard</h1>
                        </div>
                        <div class="flex items-center space-x-4">
                            <div class="hidden sm:flex flex-col items-end">
                                <span class="text-sm font-medium text-slate-900">{{ user.email }}</span>
                                <span class="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 mt-0.5">{{ user.role }}</span>
                            </div>
                            <div class="w-px h-8 bg-slate-200 hidden sm:block"></div>
                            <button @click="$emit('logout')" class="text-sm font-medium text-slate-500 hover:text-red-600 transition-colors px-2 py-1 rounded hover:bg-red-50">
                                Sign Out
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            <!-- Navigation -->
            <nav class="bg-white border-b border-slate-200 shadow-sm">
                <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div class="flex space-x-1 py-3 overflow-x-auto hide-scrollbar">
                        <button @click="currentView = 'overview'"
                                :class="currentView === 'overview' ? 'bg-slate-100 text-slate-900 shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
                                class="px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap">
                            Overview
                        </button>
                        
                        <button v-if="user.role === 'restaurant_owner'" @click="currentView = 'orders'"
                                :class="currentView === 'orders' ? 'bg-slate-100 text-slate-900 shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
                                class="px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap relative">
                            Active Orders
                            <span class="absolute top-2 right-1.5 flex h-2 w-2">
                                <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                                <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                            </span>
                        </button>

                        <button v-if="user.role === 'admin'" @click="currentView = 'restaurants'"
                                :class="currentView === 'restaurants' ? 'bg-slate-100 text-slate-900 shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
                                class="px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap">
                            Restaurants Admin
                        </button>

                        <!-- Menu Manager for Restaurant Owner & Admin -->
                        <button @click="currentView = 'menu'"
                                :class="currentView === 'menu' ? 'bg-slate-100 text-slate-900 shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
                                class="px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap">
                            Menu Management
                        </button>
                        
                        <!-- Drivers Manager -->
                        <button @click="currentView = 'drivers'"
                                :class="currentView === 'drivers' ? 'bg-slate-100 text-slate-900 shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
                                class="px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap">
                            Drivers
                        </button>
                    </div>
                </div>
            </nav>

            <!-- Content Area -->
            <main class="max-w-7xl mx-auto py-8 px-4 sm:px-6 lg:px-8">
                <component :is="currentComponent" :user="user"></component>
            </main>
        </div>
    `,
    components: { Overview, RestaurantsAdmin, MenuManager, DriversManager, OrdersManager },
    props: {
        user: Object
    },
    emits: ['logout'],
    setup(props) {
        const currentView = ref('overview');

        const currentComponent = computed(() => {
            if (currentView.value === 'overview') return 'Overview';
            if (currentView.value === 'orders' && props.user.role === 'restaurant_owner') return 'OrdersManager';
            if (currentView.value === 'restaurants' && props.user.role === 'admin') return 'RestaurantsAdmin';
            if (currentView.value === 'menu') return 'MenuManager';
            if (currentView.value === 'drivers') return 'DriversManager';
            return 'Overview';
        });

        return { currentView, currentComponent };
    }
}
