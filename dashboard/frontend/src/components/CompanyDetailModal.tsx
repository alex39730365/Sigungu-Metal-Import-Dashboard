import {
  formatKoreanEok,
  getDARTSearchUrl,
  RegionCompany,
} from "../utils/companyMapper";

interface Props {
  company: RegionCompany;
  onClose: () => void;
}

export default function CompanyDetailModal({ company, onClose }: Props) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md max-h-[90vh] overflow-y-auto rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <h2 className="text-lg font-bold leading-tight text-gray-900">
            {company.corp_name}
          </h2>
          <button
            onClick={onClose}
            className="ml-2 text-2xl leading-none text-gray-400 hover:text-gray-600"
            aria-label="닫기"
          >
            ×
          </button>
        </div>

        <dl className="space-y-2.5 text-sm">
          <div className="flex justify-between gap-2">
            <dt className="shrink-0 text-gray-500">주소</dt>
            <dd className="text-right text-gray-900">{company.adres || '-'}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="shrink-0 text-gray-500">시군구</dt>
            <dd className="text-right font-medium text-sky-700">{company.sigungu || '-'}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">업종</dt>
            <dd className="text-right text-gray-900">
              {company.induty_name || '-'} {company.induty_code ? `(${company.induty_code})` : ''}
            </dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">대표</dt>
            <dd className="text-right text-gray-900">{company.ceo_nm || '-'}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">전화</dt>
            <dd className="text-right text-gray-900">{company.phn_no || '-'}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">팩스</dt>
            <dd className="text-right text-gray-900">{company.fax_no || '-'}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">사업자번호</dt>
            <dd className="text-right text-gray-900">{company.bizr_no || '-'}</dd>
          </div>

          <div className="border-t border-gray-200 pt-3">
            <div className="mb-2 flex justify-between gap-2">
              <dt className="text-gray-500">매출액</dt>
              <dd className="text-right font-semibold text-gray-900">
                {formatKoreanEok(company.revenue)}
                {company.fin_year && company.fs_type ? (
                  <span className="ml-1 text-xs font-normal text-gray-500">
                    ({company.fin_year}년, {company.fs_type})
                  </span>
                ) : null}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-gray-500">영업이익</dt>
              <dd className="text-right font-semibold text-gray-900">
                {formatKoreanEok(company.op_profit)}
                {company.fin_year && company.fs_type ? (
                  <span className="ml-1 text-xs font-normal text-gray-500">
                    ({company.fin_year}년, {company.fs_type})
                  </span>
                ) : null}
              </dd>
            </div>
          </div>

          <div className="flex gap-4 border-t border-gray-200 pt-3 text-xs">
            {company.hm_url ? (
              <a
                href={
                  company.hm_url.startsWith("http")
                    ? company.hm_url
                    : `https://${company.hm_url}`
                }
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-600 hover:underline"
              >
                홈페이지
              </a>
            ) : null}
            <a
              href={getDARTSearchUrl(company.corp_name)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sky-600 hover:underline"
            >
              DART에서 검색
            </a>
          </div>
        </dl>
      </div>
    </div>
  );
}
