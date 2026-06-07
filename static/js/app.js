import { createApp, ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import Login from './views/Login.js';
import Dashboard from './views/Dashboard.js';
import ResetPassword from './views/ResetPassword.js';
import ForcePasswordChange from './views/ForcePasswordChange.js';

createApp({
    components: { Login, Dashboard, ResetPassword, ForcePasswordChange },
    setup() {
        const user = ref(null);
        const loading = ref(true);
        const urlParams = new URLSearchParams(window.location.search);
        const resetToken = ref(urlParams.get('reset_token') || urlParams.get('setup_token'));
        const isSetup = ref(urlParams.has('setup_token'));

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

        const handlePasswordResetDone = () => {
            // Remove token from URL and show login
            window.history.replaceState({}, document.title, window.location.pathname);
            resetToken.value = null;
        };

        const handleForcePasswordUpdated = () => {
            if (user.value) {
                user.value.requires_password_change = false;
                localStorage.setItem('user', JSON.stringify(user.value));
            }
        };

        onMounted(() => {
            if (!resetToken.value) {
                checkAuth();
            } else {
                loading.value = false;
            }
        });

        return { user, loading, resetToken, isSetup, handleLogin, handleLogout, handlePasswordResetDone, handleForcePasswordUpdated };
    }
}).mount('#app');
