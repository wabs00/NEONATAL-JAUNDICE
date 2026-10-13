import { Platform, type ImageURISource } from 'react-native';
import * as SecureStore from 'expo-secure-store';
export const API_URL=(process.env.EXPO_PUBLIC_API_URL||(Platform.OS==='android'?'http://10.0.2.2:8000':'http://localhost:8000')).replace(/\/$/,'');
let token:string|null=null;
export async function restoreSession(){token=Platform.OS==='web'?null:await SecureStore.getItemAsync('neo-session')}
export async function setSession(value:string|null){token=value;if(Platform.OS!=='web'){if(value)await SecureStore.setItemAsync('neo-session',value);else await SecureStore.deleteItemAsync('neo-session')}}
export async function request(path:string,options:RequestInit={}){const requestToken=token;const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);try{const response=await fetch(API_URL+path,{...options,credentials:'include',signal:controller.signal,headers:{...(requestToken&&Platform.OS!=='web'?{Authorization:`Bearer ${requestToken}`} : {}),...options.headers}});const body=await response.json();if(!response.ok){if(response.status===401&&token===requestToken)await setSession(null);throw new Error(Array.isArray(body.detail)?body.detail.map((x:{msg:string})=>x.msg).join('; '):body.detail||'Request failed')}return body}catch(error){if(error instanceof Error&&error.name==='AbortError')throw new Error('Connection timed out. Check the server address and retry.');throw error}finally{clearTimeout(timer)}}
export const json=(method:string,body:unknown)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
export function photoSource(id:number):ImageURISource{return {uri:`${API_URL}/assessments/${id}/image`,headers:token&&Platform.OS!=='web'?{Authorization:`Bearer ${token}`}:{}}}
