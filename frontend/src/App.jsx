import { AuthProvider } from './context/AuthContext'

function App() {
  return (
    <AuthProvider>
      <div>
        <h1>G-FlowDesk Admin Portal</h1>
        <p>Frontend scaffold initialized</p>
      </div>
    </AuthProvider>
  )
}

export default App
