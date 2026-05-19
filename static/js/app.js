import { createApp, ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import Login from './views/Login.js';
import Dashboard from './views/Dashboard.js';

createApp({
    components: { Login, Dashboard },
    setup() {
        const user = ref(null);
        const loading = ref(true);

        const checkAuth = () => {
            const token = localStorage.getItem('token');
            const storedUser = localStorage.getItem('user');
            if (token && storedUser) {
                try {
                    user.value = JSON.parse(storedUser);
                } catch (e) {
                    localStorage.removeItem('token');
                    localStorage.removeItem('user');
                }
            }
            loading.value = false;
        };

        const handleLogin = (userData) => {
            user.value = userData;
        };

        const handleLogout = () => {
            localStorage.removeItem('token');
            localStorage.removeItem('user');
            user.value = null;
        };

        onMounted(() => {
            checkAuth();
        });

        return { user, loading, handleLogin, handleLogout };
    }
}).mount('#app');
