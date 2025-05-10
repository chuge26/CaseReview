# -*- coding: utf-8 -*-
import configparser
from pathlib import Path
import fitz
from typing import Dict, Any, Optional
from io import BytesIO
import json

from alibabacloud_tea_openapi.models import Config
from alibabacloud_ocr_api20210707.client import Client as OCRClient
from alibabacloud_ocr_api20210707.models import RecognizeIdcardRequest
from alibabacloud_tea_util.models import RuntimeOptions
from alibabacloud_ocr20191230.client import Client as ocr20191230Client
from alibabacloud_ocr20191230.models import RecognizeBusinessLicenseAdvanceRequest
from alibabacloud_tea_util.client import Client as UtilClient
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_ocr_api20210707 import models as OcrModels
from alibabacloud_tea_util import models as UtilModels
import base64

class ConfigLoader:
    """配置文件加载工具类"""
    
    @staticmethod
    def load_aliyun_config() -> Dict[str, str]:
        """加载阿里云配置"""
        config = configparser.ConfigParser()
        config_path = Path(__file__).parent / 'config.ini'
        
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")
        
        config.read(config_path, encoding='utf-8')
        
        if not config.has_section('aliyun'):
            raise ValueError("配置文件中缺少 [aliyun] 节点")
        
        required_keys = ['access_key_id', 'access_key_secret', 'region_id']
        for key in required_keys:
            if not config.has_option('aliyun', key):
                raise ValueError(f"配置文件中缺少必要的配置项: {key}")
        
        return {
            'access_key_id': config['aliyun']['access_key_id'],
            'access_key_secret': config['aliyun']['access_key_secret'],
            'region_id': config['aliyun']['region_id']
        }

# 身份证模块
class Ali_IdCardOCRClient:
    """阿里云OCR客户端封装"""
    
    def __init__(self):
        self.config = ConfigLoader.load_aliyun_config()
        self.client = self._init_client()
        
    def _init_client(self) -> OCRClient:
        """初始化新版SDK客户端"""
        # 新版SDK直接使用Config对象
        config = Config(
            access_key_id=self.config['access_key_id'],
            access_key_secret=self.config['access_key_secret'],
            region_id=self.config['region_id'],
            # 新版endpoint建议在Config中直接指定
            endpoint=f'ocr-api.{self.config["region_id"]}.aliyuncs.com'
        )
        print(config)
        return OCRClient(config)
    
    def process_pdf_idcard(self, fitz_page: fitz.Page) -> Dict[str, Any]:
        """
        处理fitz.Document对象并返回结构化身份证信息
        :param fitz_doc: 通过fitz.open()获取的文档对象
        :return: 包含身份证信息的字典
        """
        # 将fitz文档转换为字节流
        pdf_pix = fitz_page.get_pixmap(dpi=300)
        pdf_bytes = pdf_pix.tobytes("png")

        recognize_request = RecognizeIdcardRequest(
            body=pdf_bytes,
            output_quality_info=True,
            output_figure=True
        )
        
        runtime = RuntimeOptions()
        
        response = self.client.recognize_idcard_with_options(recognize_request, runtime)
        return self._parse_ocr_result(response.body.to_map())

    # -*- coding: utf-8 -*-

    def _parse_ocr_result(self, raw_data: Dict) -> Dict[str, Any]:
        """完全修正的OCR结果解析方法"""
        print("原始数据为：", raw_data)
        print("原始数据类型为：", type(raw_data))
         # 解析原始数据
        data_content = raw_data.get('Data', {})
        if isinstance(data_content, str):
            try:
                data_content = json.loads(data_content)
            except json.JSONDecodeError:
                data_content = {}
        # 提取双面数据
        face_data = data_content.get('data', {}).get('face', {}).get('data', {})
        back_data = data_content.get('data', {}).get('back', {}).get('data', {}) 
        # 构建结果
        result = {
            'success': any([face_data, back_data]),
            'request_id': raw_data.get('RequestId', ''),
            'quality': {
                'is_copy': data_content.get('data', {}).get('face', {}).get('warning', {}).get('isCopy', 0) == 1,
                'quality_score': data_content.get('data', {}).get('face', {}).get('warning', {}).get('qualityScore', 0)
            },
            'sides': []
        }
        # 添加正面信息
        if front_info := self.extract_side_data(face_data, 'front'):
            result['sides'].append({
                'side': 'front',
                'data': front_info,
                'confidence': {
                    'name': data_content.get('data', {}).get('face', {}).get('prism_keyValueInfo', [{}])[0].get('valueProb', 0),
                    'id_number': data_content.get('data', {}).get('face', {}).get('prism_keyValueInfo', [{}])[-1].get('valueProb', 0)
                }
            })
        # 添加背面信息
        if back_info := self.extract_side_data(back_data, 'back'):
            result['sides'].append({
                'side': 'back',
                'data': back_info
            })
        return result

    def extract_side_data(sele, side_data: Dict, side_type: str) -> Optional[Dict]:
            """提取单面信息"""
            if not side_data:
                return None
            
            data_map = {
                'front': {
                    'name': ('name', None),
                    'gender': ('sex', None),
                    'ethnicity': ('ethnicity', None),
                    'birth_date': ('birthDate', None),
                    'address': ('address', None),
                    'id_number': ('idNumber', None)
                },
                'back': {
                    'issue_authority': ('issueAuthority', None),
                    'valid_period': ('validPeriod', None)
                }
            }
            result = {}
            for field, (src_field, _) in data_map.get(side_type, {}).items():
                if value := side_data.get(src_field):
                    result[field] = value
            return result if result else None

# 营业执照模块
class Ali_BusinessPageOCRClient:
    """阿里云OCR客户端封装"""
    
    def __init__(self):
        self.config = ConfigLoader.load_aliyun_config()
        self.client = self._init_client()
        
    def _init_client(self) -> ocr20191230Client:
        """初始化新版SDK客户端"""
        # 新版SDK直接使用Config对象
        config = Config(
            access_key_id=self.config['access_key_id'],
            access_key_secret=self.config['access_key_secret'],
            region_id=self.config['region_id'],
            # 新版endpoint建议在Config中直接指定
            endpoint=f'ocr-api.{self.config["region_id"]}.aliyuncs.com'
        )
        print(config)
        return OCRClient(config)
    
    def process_pdf_business_license(self, fitz_page: fitz.Page) -> Dict[str, Any]:
        """
        处理fitz.Document对象并返回结构化营业执照信息
        :param fitz_doc: 通过fitz.open()获取的文档对象
        :return: 包含营业执照信息的字典
        """
        # 将fitz文档转换为字节流
        pdf_pix = fitz_page.get_pixmap(dpi=450)
        pdf_bytes = pdf_pix.tobytes("png")
        # 创建请求对象
        request = OcrModels.RecognizeBusinessLicenseRequest(
            body = pdf_bytes
        )
        # 创建运行时选项
        runtime = RuntimeOptions()
        # 调用OCR API
        response = self.client.recognize_business_license_with_options(request, runtime)
        # 解析响应
        return response.body.to_map()
    


