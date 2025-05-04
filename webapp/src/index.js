import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import reportWebVitals from './reportWebVitals';
import axios from 'axios'
// Importing the Bootstrap CSS
import 'bootstrap/dist/css/bootstrap.min.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
axios.defaults.baseURL = "http://tf-lb-20250504110929704200000003-212004373.us-east-1.elb.amazonaws.com"  // <------ A modifier quand vous aller tester avec vos instances EC2 et votre load balancer !!!

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);


reportWebVitals();
