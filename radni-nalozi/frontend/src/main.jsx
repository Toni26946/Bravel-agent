import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './auth'
import { JezikProvider } from './i18n'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <JezikProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </JezikProvider>
    </BrowserRouter>
  </React.StrictMode>
)
